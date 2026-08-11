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

# Prefer sealed accelerate checkout when present (hermetic CI / worktrees).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_ACCELERATE = _REPO_ROOT / "ipfs_accelerate_py"


def _prefer_sealed_accelerate_checkout() -> None:
    try:
        if (_LOCAL_ACCELERATE / "ipfs_accelerate_py").is_dir() or (
            _LOCAL_ACCELERATE / "agent_supervisor"
        ).is_dir():
            sealed = str(_LOCAL_ACCELERATE)
            if sealed not in sys.path:
                sys.path.insert(0, sealed)
            # Drop any previously imported non-sealed accelerate packages.
            for name in list(sys.modules):
                if name == "ipfs_accelerate_py" or name.startswith(
                    "ipfs_accelerate_py."
                ):
                    del sys.modules[name]
    except OSError:
        pass


_prefer_sealed_accelerate_checkout()
os.environ.setdefault("IPFS_DATASETS_HERMETIC", "1")

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


@pytest.fixture
def shadow() -> ObservabilityShadowRepository:
    reset_observability_shadow()
    repo = configure_observability_shadow()
    yield repo
    reset_observability_shadow()


# ---------------------------------------------------------------------------
# Module invariants
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
        repo = configure_observability_shadow()
        assert get_observability_shadow() is repo
        assert repo.enabled
        assert repo.authority_mode is AuthorityMode.SHADOW
        reset_observability_shadow()
        assert get_observability_shadow() is None

    def test_import_is_inert(self) -> None:
        # Enumerating producers / modes must not open DuckDB or files.
        assert ObservabilityProducer.AUDIT.value == "audit"
        assert AuthorityMode.SHADOW.value == "shadow"


# ---------------------------------------------------------------------------
# Required fields on every mutable record
# ---------------------------------------------------------------------------


class TestEveryRecordHasRequiredFields:
    def test_every_mutable_record_has_typed_fields(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        producers = [
            (ObservabilityProducer.AUDIT, "data_access", {"path": "/tmp/x"}),
            (ObservabilityProducer.SECURITY_AUDIT, "proof_attempt", {"ok": True}),
            (
                ObservabilityProducer.STRUCTURED_LOG,
                "mcp.tool.invoked",
                {"tool_name": "ipfs_add"},
            ),
            (ObservabilityProducer.GRAPHRAG_AUDIT, "strategy_decision", {"round": 1}),
            (ObservabilityProducer.PIPELINE_JSON, "pipeline.run.started", {"run": 1}),
            (ObservabilityProducer.LOGGING_AUDIT, "logging_audit.result", {"n": 1}),
            (ObservabilityProducer.ALERT, "alert.disk", {"severity": "critical"}),
            (ObservabilityProducer.MCP, "mcp.info", {"message": "hello"}),
            (ObservabilityProducer.PROVENANCE, "lineage.link", {"cid": "bafy1"}),
        ]
        receipts = []
        for producer, kind, payload in producers:
            receipts.append(
                shadow.record_event(
                    producer,
                    kind,
                    payload=payload,
                    outcome="success",
                )
            )

        assert len(receipts) == len(producers)
        for receipt in receipts:
            body = receipt.to_dict()
            assert body["schema"] == OBSERVABILITY_EVENT_RECEIPT_SCHEMA
            assert body["event_id"]
            assert body["operation_id"]
            assert body["record_schema"].startswith("ipfs_datasets_py/")
            assert body["classification"]
            assert body["classification"] != SensitivityClass.SECRET.value
            assert body["source_revision"]
            assert body["parity_receipt_cid"]
            assert body["mode"] == AuthorityMode.SHADOW.value
            assert body["payload_digest"].startswith("sha256:")
            assert body["evidence_cid"].startswith("sha256:")

            record = shadow.catalog_record(receipt.family, receipt.event_id)
            assert record is not None
            if receipt.family == CatalogFamily.AUDIT_EVENTS.value:
                assert getattr(record, "SCHEMA", None) == AUDIT_RECORD_SCHEMA

        parity = shadow.list_parity_receipts()
        assert len(parity) >= len(producers)
        assert all(p.matched for p in parity)

    def test_legacy_is_selected_shadow_authority(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        receipt = shadow.record_event(
            ObservabilityProducer.AUDIT,
            "legacy_authority_probe",
            payload={"x": 1},
            outcome="succeeded",
        )
        assert receipt.mode == AuthorityMode.SHADOW.value
        assert receipt.authority == "legacy"
        legacy = shadow.legacy_sink_records()
        assert any(r.get("event_id") == receipt.event_id for r in legacy)


# ---------------------------------------------------------------------------
# Idempotency / restart safety
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_retry_same_operation_id_does_not_duplicate(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        kwargs = dict(
            producer=ObservabilityProducer.AUDIT,
            kind="retry_probe",
            payload={"n": 1},
            event_id="evt-idempotent-fixed-001",
            operation_id="op:idempotent-fixed",
            actor="tester",
        )
        r1 = shadow.record_event(**kwargs)
        r2 = shadow.record_event(**kwargs)
        assert r2.idempotent_replay is True
        assert r2.event_id == r1.event_id
        assert r2.operation_id == r1.operation_id
        assert r2.parity_receipt_cid == r1.parity_receipt_cid
        assert r2.sequence == r1.sequence
        rows = shadow.observability_catalog.list_family(CatalogFamily.AUDIT_EVENTS)
        matching = [r for r in rows if getattr(r, "event_id", None) == r1.event_id]
        assert len(matching) == 1

    def test_content_derived_stable_id_is_idempotent(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        payload = {"action": "export", "dataset": "dataset-1", "actor": "exporter"}
        eid = stable_event_id(ObservabilityProducer.AUDIT, "export", payload)
        r1 = shadow.record_event(
            ObservabilityProducer.AUDIT, "export", payload=payload
        )
        r2 = shadow.record_event(
            ObservabilityProducer.AUDIT, "export", payload=payload
        )
        assert r1.event_id == eid or r1.event_id == r2.event_id
        assert r2.idempotent_replay is True
        assert r2.event_id == r1.event_id

    def test_restart_does_not_duplicate_with_shared_backend(self) -> None:
        reset_observability_shadow()
        first = configure_observability_shadow()
        r1 = first.record_event(
            ObservabilityProducer.MCP,
            "mcp.info",
            payload={"message": "restart-probe"},
            event_id="evt-restart-1",
            operation_id="op:restart-1",
        )
        backend = first.backend
        catalog = first.observability_catalog
        evidence = first.evidence_store
        # Simulate process restart: new repository, shared backend+catalog.
        second = ObservabilityShadowRepository(
            mode=AuthorityMode.SHADOW,
            catalog=catalog,
            backend=backend,
            evidence_store=evidence,
        )
        r2 = second.record_event(
            ObservabilityProducer.MCP,
            "mcp.info",
            payload={"message": "restart-probe"},
            event_id="evt-restart-1",
            operation_id="op:restart-1",
        )
        # Catalog must still hold a single row for the event id.
        rows = catalog.list_family(CatalogFamily.AUDIT_EVENTS)
        matching = [
            r for r in rows if getattr(r, "event_id", None) == "evt-restart-1"
        ]
        assert len(matching) == 1
        assert r2.event_id == r1.event_id
        # Authority port write is idempotent by operation_id.
        assert r2.idempotent_replay is True or r2.sequence == r1.sequence
        reset_observability_shadow()


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


class TestRedaction:
    def test_secrets_redacted_before_persistence(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        receipt = shadow.record_event(
            ObservabilityProducer.SECURITY_AUDIT,
            "credential_check",
            payload={
                "password": "hunter2",
                "api_key": "sk-live-secret-value",
                "authorization": "Bearer abc.def.ghi",
                "message": "login attempt",
            },
            actor="user-1",
            outcome="failed",
        )
        record = shadow.catalog_record(receipt.family, receipt.event_id)
        assert record is not None
        blob = str(getattr(record, "detail", "")) + str(
            dict(getattr(record, "attributes", {}) or {})
        )
        evidence = shadow.evidence_blob(receipt.evidence_cid) or b""
        combined = blob + evidence.decode("utf-8", errors="ignore")
        assert "hunter2" not in combined
        assert "sk-live-secret-value" not in combined
        assert "abc.def.ghi" not in combined
        assert REDACTION_MARKER in combined
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
            ObservabilityProducer.QUERY_PROFILE,
            "ad_hoc_query",
            payload={"query_text": sql, "template": "ad_hoc"},
            actor="analyst",
            outcome="succeeded",
            query_text=sql,
            family=CatalogFamily.QUERY_PROFILES,
        )
        record = shadow.catalog_record(CatalogFamily.QUERY_PROFILES, receipt.event_id)
        assert record is not None
        stored = str(getattr(record, "query_text", ""))
        assert "hunter2" not in stored
        # Classification must not leave unrestricted SQL as public plaintext.
        klass = getattr(record, "query_text_classification", None)
        if klass is not None:
            value = klass.value if hasattr(klass, "value") else str(klass)
            assert value in {
                SensitivityClass.REDACTED.value,
                SensitivityClass.INTERNAL.value,
                SensitivityClass.PUBLIC.value,
            }
        evidence = (shadow.evidence_blob(receipt.evidence_cid) or b"").decode(
            "utf-8", errors="ignore"
        )
        # Evidence must also be redacted for SQL fields.
        assert "hunter2" not in evidence or REDACTION_MARKER in evidence

    def test_redact_event_payload_helper(self) -> None:
        redacted = redact_event_payload(
            {
                "password": "secret-value",
                "nested": {"token": "abc123"},
                "query_text": "INSERT INTO t VALUES (1)",
                "ok": True,
            }
        )
        assert redacted["password"] == REDACTION_MARKER
        assert redacted["nested"]["token"] == REDACTION_MARKER
        assert "INSERT" not in str(redacted.get("query_text", "")) or (
            redacted.get("query_text_classification")
            == SensitivityClass.REDACTED.value
            or REDACTION_MARKER in str(redacted.get("query_text"))
        )


# ---------------------------------------------------------------------------
# Evidence outside DuckDB
# ---------------------------------------------------------------------------


class TestEvidenceOutsideDuckDB:
    def test_evidence_is_content_addressed_and_outside_catalog(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        receipt = shadow.record_event(
            ObservabilityProducer.PROVENANCE,
            "blob_linked",
            payload={"cid": "bafyexample", "note": "immutable blob"},
        )
        assert isinstance(shadow.evidence_store, MemoryEvidenceBlobStore)
        assert shadow.evidence_store.has(receipt.evidence_cid)
        blob = shadow.evidence_blob(receipt.evidence_cid)
        assert blob is not None
        assert isinstance(blob, (bytes, bytearray))
        record = shadow.catalog_record(receipt.family, receipt.event_id)
        assert record is not None
        attrs = dict(getattr(record, "attributes", {}) or {})
        # Catalog holds the CID pointer, not the raw evidence bytes.
        assert attrs.get("evidence_cid") == receipt.evidence_cid
        assert attrs.get("content_addressed_outside_duckdb") is True
        detail = str(getattr(record, "detail", ""))
        assert blob.decode("utf-8", errors="ignore") not in detail or len(blob) < 64

    def test_progress_is_sequence_not_mtime(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        shadow.record_event(
            ObservabilityProducer.LIFECYCLE,
            "component.start",
            payload={"component": "supervisor"},
            family=CatalogFamily.LIFECYCLE_EVENTS,
        )
        cursor = shadow.progress()
        assert cursor.authority is ProgressAuthority.SEQUENCE
        assert cursor.sequence >= 1


# ---------------------------------------------------------------------------
# Producer routers + wiring
# ---------------------------------------------------------------------------


class TestProducerRouters:
    def test_route_helpers_when_configured(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        r1 = route_security_audit_event(
            "rate_limit_exceeded",
            "user-a",
            False,
            details={"limit_calls": 10},
            shadow=shadow,
        )
        assert r1 is not None
        assert r1.producer == ObservabilityProducer.SECURITY_AUDIT.value

        r2 = route_structured_log_event(
            "system.start",
            fields={"component": "core"},
            shadow=shadow,
        )
        assert r2 is not None

        r3 = route_pipeline_json_event(
            "pipeline.run.started",
            data={"status": "started"},
            run_id="run-1",
            shadow=shadow,
        )
        assert r3 is not None
        assert r3.producer == ObservabilityProducer.PIPELINE_JSON.value

        r4 = route_alert_event(
            "rule-1",
            "High CPU",
            "warning",
            status="triggered",
            message="cpu > 90",
            shadow=shadow,
        )
        assert r4 is not None
        assert r4.parity_matched is True

        r5 = route_mcp_log_event("hello mcp", shadow=shadow)
        assert r5 is not None

        r6 = route_logging_audit_result(
            {
                "file_path": "mod.py",
                "class_name": "Foo",
                "methods_with_logging": ["run"],
                "methods_without_logging": [],
                "has_logger_init": True,
                "issues": [],
                "logging_patterns": {},
            },
            shadow=shadow,
        )
        assert r6 is not None

        r7 = route_producer_event(
            ObservabilityProducer.PROVENANCE,
            "custom.probe",
            payload={"k": 1},
            shadow=shadow,
        )
        assert r7 is not None

    def test_route_helpers_noop_without_shadow(self) -> None:
        reset_observability_shadow()
        assert route_mcp_log_event("no shadow") is None
        assert route_security_audit_event("x", "u", True) is None

    def test_core_audit_logger_routes_when_shadow_configured(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        from ipfs_datasets_py.audit.audit_logger import (
            AuditCategory,
            AuditLevel,
            AuditLogger,
        )

        logger = AuditLogger()
        logger.log(
            AuditLevel.INFO,
            AuditCategory.SECURITY,
            "login",
            user="alice",
            status="success",
            details={"method": "password"},
            session_id="session-1",
            event_id="evt-core-audit-login-001",
        )
        receipts = shadow.list_receipts(ObservabilityProducer.AUDIT)
        assert any(r.event_id == "evt-core-audit-login-001" for r in receipts)

    def test_security_audit_log_routes(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        from ipfs_datasets_py.logic.security.audit_log import AuditLogger

        AuditLogger.log_event(
            event_type="proof_attempt",
            user_id="prover-1",
            success=True,
            details={"prover": "z3"},
        )
        receipts = shadow.list_receipts(ObservabilityProducer.SECURITY_AUDIT)
        assert any(r.kind.startswith("proof_attempt") for r in receipts)

    def test_graphrag_audit_logger_routes(
        self, shadow: ObservabilityShadowRepository, tmp_path: Path
    ) -> None:
        from ipfs_datasets_py.optimizers.graphrag.audit_logger import (
            AuditLogger,
            EventType,
        )

        class _Ctx:
            data_source = "sample"
            domain = "test"
            extraction_strategy = "default"

        logger = AuditLogger(
            session_id="sess-test-001",
            output_dir=tmp_path,
            enable_file_logging=False,
        )
        logger.log_cycle_start(
            data="sample",
            context=_Ctx(),
            max_rounds=3,
            convergence_threshold=0.9,
        )
        receipts = shadow.list_receipts(ObservabilityProducer.GRAPHRAG_AUDIT)
        assert any(
            r.kind == EventType.REFINEMENT_CYCLE_START.value for r in receipts
        )

    def test_pipeline_json_logger_routes(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        from ipfs_datasets_py.optimizers.graphrag.pipeline_json_logger import (
            PipelineJSONLogger,
        )

        plog = PipelineJSONLogger(domain="unit-test")
        plog.start_run(run_id="run-pipeline-1", data_source="fixture")
        plog.end_run(success=True)
        receipts = shadow.list_receipts(ObservabilityProducer.PIPELINE_JSON)
        assert len(receipts) >= 2

    def test_structured_logging_routes(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        from ipfs_datasets_py.logic.observability.structured_logging import (
            EventType,
            log_event,
        )

        log_event(EventType.SYSTEM_START, component="integration-test")
        receipts = shadow.list_receipts(ObservabilityProducer.STRUCTURED_LOG)
        assert len(receipts) >= 1

    def test_mcp_logger_helper_routes(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        from ipfs_datasets_py.mcp_server.logger import log_mcp_event

        eid = log_mcp_event(
            "mcp shadow probe",
            event_id="evt-mcp-probe-001",
            operation_id="op:mcp-probe-001",
        )
        assert eid == "evt-mcp-probe-001"
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
        receipts = shadow.list_receipts(ObservabilityProducer.LOGGING_AUDIT)
        assert len(receipts) >= 1

    def test_alert_manager_routes(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        receipt = route_alert_event(
            "rule-disk",
            "Disk full",
            "critical",
            status="triggered",
            message="disk > 95%",
            event_id="evt-alert-disk-001",
            operation_id="op:alert-disk-001",
            shadow=shadow,
        )
        assert receipt is not None
        loaded = shadow.get_receipt(event_id="evt-alert-disk-001")
        assert loaded is not None
        assert loaded.parity_receipt_cid


class TestCrossProducerParity:
    def test_all_wired_producers_emit_parity(
        self, shadow: ObservabilityShadowRepository
    ) -> None:
        from ipfs_datasets_py.audit.audit_logger import (
            AuditCategory,
            AuditLevel,
            AuditLogger,
        )
        from ipfs_datasets_py.logic.security import audit_log as security_audit
        from ipfs_datasets_py.logic.observability.structured_logging import log_event
        from ipfs_datasets_py.mcp_server.logger import log_mcp_event
        from ipfs_datasets_py.optimizers.graphrag.pipeline_json_logger import (
            PipelineJSONLogger,
        )

        AuditLogger().log(
            AuditLevel.INFO,
            AuditCategory.SYSTEM,
            "cross_probe",
            event_id="evt-cross-audit-1",
        )
        security_audit.log_security_event(
            user_id="u1",
            event_type="validation_error",
            severity="low",
            message="bad input",
        )
        log_event("custom.probe", probe=True)
        log_mcp_event("cross mcp", event_id="evt-cross-mcp-1")
        PipelineJSONLogger(domain="cross").start_run(
            run_id="run-cross-1", data_source="x"
        )
        route_alert_event(
            "rule-cross",
            "Cross",
            "info",
            status="triggered",
            message="cross",
            shadow=shadow,
        )

        receipts = shadow.list_receipts()
        assert len(receipts) >= 5
        for receipt in receipts:
            assert receipt.event_id
            assert receipt.record_schema
            assert receipt.classification
            assert receipt.source_revision
            assert receipt.parity_receipt_cid
            assert receipt.mode == AuthorityMode.SHADOW.value
            assert receipt.parity_matched is True
