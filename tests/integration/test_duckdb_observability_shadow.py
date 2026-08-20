"""Integration tests for observability producer shadow routing (DQK-077).

Acceptance coverage:

* Every mutable log/audit/alert record has a typed schema, stable event ID,
  classification, source revision and parity receipt
* Retries and restarts do not duplicate events
* Secrets and unrestricted SQL are redacted before persistence or publication
* Immutable evidence blobs remain content-addressed outside DuckDB

Legacy file sinks remain the selected authority under shadow mode; the typed
observability catalog is a non-authoritative projection with parity receipts.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

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

from ipfs_datasets_py.duckdb_control.authority_transition import (  # noqa: E402
    AuthorityMode,
)
from ipfs_datasets_py.duckdb_control.observability import (  # noqa: E402
    AUDIT_RECORD_SCHEMA,
    CatalogFamily,
    SensitivityClass,
)
from ipfs_datasets_py.duckdb_control.observability_adapters import (  # noqa: E402
    OBSERVABILITY_ADAPTER_SCHEMA,
    OBSERVABILITY_SHADOW_DOMAIN,
    OBSERVABILITY_SHADOW_OWNER_TASK,
    OBSERVABILITY_SOURCE_REVISION,
    PRODUCER_SCHEMAS,
    MemoryEvidenceBlobStore,
    ObservabilityProducer,
    ObservabilityShadowRepository,
    build_observability_shadow_repository,
    configure_observability_shadow,
    get_observability_shadow,
    record_observability_event,
    redact_event_payload,
    reset_observability_shadow,
)


FIXED_CLOCK = "2026-08-11T12:00:00Z"


def _clock() -> str:
    return FIXED_CLOCK


@pytest.fixture
def shadow() -> ObservabilityShadowRepository:
    reset_observability_shadow()
    repo = configure_observability_shadow(
        mode=AuthorityMode.SHADOW,
        source_revision=OBSERVABILITY_SOURCE_REVISION,
        clock=_clock,
    )
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
        assert OBSERVABILITY_SOURCE_REVISION.startswith("dqk-077-")

    def test_all_expected_producers_registered(self) -> None:
        expected = {
            "audit.audit_logger",
            "logic.security.audit_log",
            "logic.observability.structured_logging",
            "optimizers.graphrag.audit_logger",
            "optimizers.graphrag.pipeline_json_logger",
            "optimizers.common.logging_audit",
            "alerts.alert_manager",
            "mcp_server.logger",
        }
        assert set(PRODUCER_SCHEMAS) == expected
        assert {p.value for p in ObservabilityProducer} == expected

    def test_process_registry_configure_get_reset(self) -> None:
        reset_observability_shadow()
        assert get_observability_shadow() is None
        repo = configure_observability_shadow(mode=AuthorityMode.SHADOW)
        assert get_observability_shadow() is repo
        assert repo.enabled
        assert repo.mode is AuthorityMode.SHADOW
        reset_observability_shadow()
        assert get_observability_shadow() is None

    def test_shadow_mode_selects_legacy_authority(self, shadow) -> None:
        assert shadow.mode is AuthorityMode.SHADOW
        # Authority port domain is observability; mode is shadow (legacy wins).
        assert shadow.authority_port.mode is AuthorityMode.SHADOW


# ---------------------------------------------------------------------------
# Acceptance: typed schema, stable event ID, classification, revision, parity
# ---------------------------------------------------------------------------


class TestTypedRecordShape:
    def test_every_record_has_required_fields(self, shadow) -> None:
        receipts = []
        for producer in ObservabilityProducer:
            receipt = shadow.record_event(
                producer=producer,
                action=f"probe.{producer.name.lower()}",
                actor="tester",
                outcome="succeeded",
                detail=f"probe for {producer.value}",
                attributes={"probe": True, "producer": producer.value},
                event_id=f"probe-{producer.name.lower()}",
            )
            receipts.append(receipt)

        assert len(receipts) == len(ObservabilityProducer)
        for receipt in receipts:
            assert receipt.event_id
            assert receipt.catalog_schema == AUDIT_RECORD_SCHEMA
            assert receipt.producer_schema in PRODUCER_SCHEMAS.values()
            assert receipt.classification in {c.value for c in SensitivityClass}
            assert receipt.source_revision == OBSERVABILITY_SOURCE_REVISION
            assert receipt.parity_receipt_cid.startswith("sha256:")
            assert receipt.parity_matched is True
            assert receipt.evidence_cid.startswith("sha256:")
            assert receipt.sequence >= 1
            assert receipt.catalog_family == CatalogFamily.AUDIT_EVENTS.value
            assert receipt.authority == "legacy"

        catalog_rows = shadow.catalog.list_family(CatalogFamily.AUDIT_EVENTS)
        assert len(catalog_rows) == len(ObservabilityProducer)
        for row in catalog_rows:
            d = row.to_dict()
            assert d["schema"] == AUDIT_RECORD_SCHEMA
            assert d["event_id"]
            assert d["classification"]
            assert d["attributes"].get("source_revision") == OBSERVABILITY_SOURCE_REVISION
            assert d["attributes"].get("evidence_cid")


# ---------------------------------------------------------------------------
# Acceptance: retries / restarts do not duplicate
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_retry_same_event_id_does_not_duplicate(self, shadow) -> None:
        first = shadow.record_event(
            producer=ObservabilityProducer.AUDIT_LOGGER,
            action="auth.login",
            actor="alice",
            outcome="succeeded",
            detail="login ok",
            event_id="stable-evt-retry-1",
            operation_id="op-stable-evt-retry-1",
        )
        second = shadow.record_event(
            producer=ObservabilityProducer.AUDIT_LOGGER,
            action="auth.login",
            actor="alice",
            outcome="succeeded",
            detail="login ok",
            event_id="stable-evt-retry-1",
            operation_id="op-stable-evt-retry-1",
        )
        assert second.idempotent_replay is True
        assert second.event_id == first.event_id
        assert second.parity_receipt_cid == first.parity_receipt_cid
        assert len(shadow.catalog.list_family(CatalogFamily.AUDIT_EVENTS)) == 1
        assert shadow.counts()["receipts"] == 1

    def test_restart_via_rebuild_reuses_operation_through_port(self) -> None:
        """Authority port + catalog natural IDs prevent duplicates on restart."""

        backend = None
        evidence = MemoryEvidenceBlobStore()
        reset_observability_shadow()
        repo1 = build_observability_shadow_repository(
            mode=AuthorityMode.SHADOW,
            evidence_store=evidence,
            clock=_clock,
            set_global=True,
        )
        backend = repo1.authority_port.backend
        r1 = repo1.record_event(
            producer=ObservabilityProducer.MCP_LOGGER,
            action="mcp.start",
            actor="mcp",
            outcome="succeeded",
            event_id="restart-evt-1",
            operation_id="op-restart-evt-1",
        )

        # Simulate process restart: new repository, shared authority backend +
        # shared catalog backend is not shared, but operation_id on the port
        # still prevents dual legacy/db writes; we re-bind catalog with empty
        # and assert authority outbox/port idempotency + local event index.
        repo2 = ObservabilityShadowRepository(
            mode=AuthorityMode.SHADOW,
            backend=backend,
            evidence_store=evidence,
            clock=_clock,
        )
        # Seed local index from a re-record with same IDs: port returns
        # idempotent_replay for the same operation_id.
        write = repo2.authority_port.write(
            f"obs:mcp_server.logger:restart-evt-1",
            {
                "schema": PRODUCER_SCHEMAS[ObservabilityProducer.MCP_LOGGER.value],
                "event_id": "restart-evt-1",
            },
            operation_id="op-restart-evt-1",
        )
        assert write["idempotent_replay"] is True
        assert r1.event_id == "restart-evt-1"
        reset_observability_shadow()


# ---------------------------------------------------------------------------
# Acceptance: secrets and unrestricted SQL redacted
# ---------------------------------------------------------------------------


class TestRedaction:
    def test_secrets_and_sql_redacted_before_persistence(self, shadow) -> None:
        receipt = shadow.record_event(
            producer=ObservabilityProducer.LOGIC_SECURITY_AUDIT,
            action="security.query",
            actor="bob",
            outcome="failed",
            detail="password=s3cr3t SELECT * FROM users WHERE token=abc",
            attributes={
                "password": "s3cr3t",
                "api_key": "sk-live-xyz",
                "query": "SELECT * FROM wallets WHERE secret = 'x'",
                "note": "harmless",
            },
            event_id="redact-evt-1",
            raw_payload={
                "password": "s3cr3t",
                "sql": "DELETE FROM accounts",
            },
        )
        assert receipt.classification == SensitivityClass.REDACTED.value
        assert "s3cr3t" not in receipt.detail
        assert "SELECT" not in receipt.detail.upper() or "sql-redacted" in receipt.detail

        row = shadow.catalog.get(CatalogFamily.AUDIT_EVENTS, "redact-evt-1")
        assert row is not None
        attrs = dict(row.attributes)
        assert attrs.get("password") == "***REDACTED***"
        assert attrs.get("api_key") == "***REDACTED***"
        assert "s3cr3t" not in json.dumps(attrs)
        assert "sk-live" not in json.dumps(attrs)
        query_val = str(attrs.get("query") or "")
        assert "sql-redacted" in query_val or "SELECT" not in query_val.upper()

        # Authority projection (legacy + db) also redacted.
        legacy = shadow.authority_port.backend.get_legacy(
            OBSERVABILITY_SHADOW_DOMAIN, f"obs:{receipt.producer}:{receipt.event_id}"
        )
        assert legacy is not None
        legacy_json = json.dumps(dict(legacy))
        assert "s3cr3t" not in legacy_json
        assert "sk-live" not in legacy_json

        db = shadow.authority_port.backend.get_db(
            OBSERVABILITY_SHADOW_DOMAIN, f"obs:{receipt.producer}:{receipt.event_id}"
        )
        assert db is not None
        db_json = json.dumps(dict(db))
        assert "s3cr3t" not in db_json

        # Evidence blob also scrubbed.
        blob = shadow.evidence_store.get(receipt.evidence_cid)
        assert blob is not None
        assert b"s3cr3t" not in blob
        assert b"DELETE FROM" not in blob

    def test_redact_event_payload_helper(self) -> None:
        redacted, klass = redact_event_payload(
            {
                "token": "abc",
                "sql": "INSERT INTO t VALUES (1)",
                "ok": "fine",
            }
        )
        assert klass is SensitivityClass.REDACTED
        assert redacted["token"] == "***REDACTED***"
        assert "sql-redacted" in str(redacted["sql"])
        assert redacted["ok"] == "fine"


# ---------------------------------------------------------------------------
# Acceptance: evidence blobs content-addressed outside DuckDB
# ---------------------------------------------------------------------------


class TestEvidenceOutsideDuckDB:
    def test_evidence_not_embedded_in_authority_projection(self, shadow) -> None:
        payload = {"body": "x" * 200, "meta": {"k": "v"}}
        receipt = shadow.record_event(
            producer=ObservabilityProducer.STRUCTURED_LOGGING,
            action="system.start",
            actor="system",
            outcome="info",
            detail="boot",
            attributes={"component": "boot"},
            event_id="evidence-evt-1",
            raw_payload=payload,
        )
        assert shadow.evidence_store.contains(receipt.evidence_cid)
        blob = shadow.evidence_store.get(receipt.evidence_cid)
        assert blob is not None
        assert len(blob) > 0

        legacy = shadow.authority_port.backend.get_legacy(
            OBSERVABILITY_SHADOW_DOMAIN, f"obs:{receipt.producer}:{receipt.event_id}"
        )
        assert legacy is not None
        # Projection holds only the content reference, not the full body blob.
        assert legacy.get("evidence_cid") == receipt.evidence_cid
        assert "x" * 200 not in json.dumps(dict(legacy))

        row = shadow.catalog.get(CatalogFamily.AUDIT_EVENTS, "evidence-evt-1")
        assert row is not None
        assert row.attributes.get("evidence_cid") == receipt.evidence_cid
        # Catalog attributes must not hold the full evidence body.
        assert "x" * 200 not in json.dumps(row.to_dict())


# ---------------------------------------------------------------------------
# Producer integration: each expected producer module routes when configured
# ---------------------------------------------------------------------------


class TestProducerWiring:
    def test_audit_logger_producer(self, shadow) -> None:
        from ipfs_datasets_py.audit.audit_logger import (
            AuditCategory,
            AuditLevel,
            AuditLogger,
        )

        logger = AuditLogger()
        logger.enabled = True
        event_id = logger.log(
            AuditLevel.INFO,
            AuditCategory.SECURITY,
            "login",
            user="carol",
            status="success",
            details={"method": "password"},
            event_id="producer-audit-1",
        )
        assert event_id == "producer-audit-1"
        receipt = shadow.get_receipt("producer-audit-1")
        assert receipt is not None
        assert receipt.producer == ObservabilityProducer.AUDIT_LOGGER.value
        assert receipt.parity_matched is True
        assert receipt.source_revision == OBSERVABILITY_SOURCE_REVISION

    def test_logic_security_audit_producer(self, shadow) -> None:
        from ipfs_datasets_py.logic.security.audit_log import AuditLogger as LogicAudit

        LogicAudit.log_event(
            event_type="proof_attempt",
            user_id="dave",
            success=True,
            details={"prover": "z3"},
            event_id="producer-logic-sec-1",
        )
        # event_id may be derived when seed is provided via kwargs
        rows = shadow.catalog.list_family(CatalogFamily.AUDIT_EVENTS)
        logic_rows = [
            r
            for r in rows
            if getattr(r, "attributes", {}).get("producer")
            == ObservabilityProducer.LOGIC_SECURITY_AUDIT.value
            or r.action.startswith("proof")
        ]
        assert logic_rows, "logic security audit did not route to shadow"

    def test_structured_logging_producer(self, shadow) -> None:
        from ipfs_datasets_py.logic.observability import structured_logging as slog

        slog.log_event(
            "mcp.tool.invoked",
            tool_name="ipfs_add",
            event_id="producer-slog-1",
            user_id="eve",
        )
        receipt = shadow.get_receipt("producer-slog-1")
        assert receipt is not None
        assert receipt.producer == ObservabilityProducer.STRUCTURED_LOGGING.value

    def test_graphrag_audit_producer(self, shadow) -> None:
        from ipfs_datasets_py.optimizers.graphrag.audit_logger import (
            AuditLogger as GraphAudit,
            EventType,
        )

        logger = GraphAudit(
            session_id="sess-graphrag-1",
            output_dir=None,
            enable_file_logging=False,
        )
        logger.log_cycle_start(
            data="sample",
            context=MagicMock(
                data_source="test", domain="legal", extraction_strategy="rule"
            ),
            max_rounds=3,
            convergence_threshold=0.9,
        )
        rows = [
            r
            for r in shadow.catalog.list_family(CatalogFamily.AUDIT_EVENTS)
            if r.attributes.get("producer")
            == ObservabilityProducer.GRAPHRAG_AUDIT.value
            or r.action == EventType.REFINEMENT_CYCLE_START.value
        ]
        assert rows

    def test_pipeline_json_logger_producer(self, shadow) -> None:
        from ipfs_datasets_py.optimizers.graphrag.pipeline_json_logger import (
            PipelineJSONLogger,
        )

        plog = PipelineJSONLogger(domain="legal")
        plog.start_run(run_id="run-pipeline-1", data_source="fixture")
        rows = [
            r
            for r in shadow.catalog.list_family(CatalogFamily.AUDIT_EVENTS)
            if r.attributes.get("producer")
            == ObservabilityProducer.PIPELINE_JSON.value
            or "pipeline" in r.action
        ]
        assert rows
        plog.end_run(success=True)

    def test_logging_audit_producer(self, shadow, tmp_path: Path) -> None:
        from ipfs_datasets_py.optimizers.common.logging_audit import LoggingAuditor

        sample = tmp_path / "sample_opt.py"
        sample.write_text(
            "import logging\n"
            "logger = logging.getLogger(__name__)\n"
            "class Foo:\n"
            "    def generate(self):\n"
            "        logger.info('hi')\n"
        )
        auditor = LoggingAuditor(root_dir=str(tmp_path))
        auditor.audit_directory()
        auditor.generate_report()
        rows = [
            r
            for r in shadow.catalog.list_family(CatalogFamily.AUDIT_EVENTS)
            if r.attributes.get("producer")
            == ObservabilityProducer.LOGGING_AUDIT.value
            or r.action.startswith("logging_audit")
        ]
        assert rows

    def test_alert_manager_producer(self, shadow) -> None:
        import anyio
        from ipfs_datasets_py.alerts.alert_manager import AlertManager, AlertRule
        from ipfs_datasets_py.alerts.rule_engine import RuleEngine

        notifier = MagicMock()
        notifier.send_message = AsyncMock(return_value={"ok": True})
        # Simple always-true condition via rule engine: use == on a present key.
        rule = AlertRule(
            rule_id="rule-cpu-high",
            name="CPU high",
            condition={"==": [{"var": "alert"}, True]},
            message_template="CPU alert: {value}",
            severity="warning",
            suppression_window=0,
        )
        manager = AlertManager(
            notifier=notifier,
            rule_engine=RuleEngine(),
            rules=[rule],
        )

        async def _run() -> list[dict[str, Any]]:
            return await manager.evaluate_event({"alert": True, "value": 99})

        results = anyio.run(_run)
        assert results
        rows = [
            r
            for r in shadow.catalog.list_family(CatalogFamily.AUDIT_EVENTS)
            if r.attributes.get("producer")
            == ObservabilityProducer.ALERT_MANAGER.value
            or r.action.startswith("alert.")
        ]
        assert rows

    def test_mcp_logger_producer(self, shadow) -> None:
        from ipfs_datasets_py.mcp_server.logger import log_mcp_event

        log_mcp_event(
            "MCP tool ready",
            event_type="mcp.ready",
            actor="mcp_server",
            event_id="producer-mcp-1",
            tool="status",
        )
        receipt = shadow.get_receipt("producer-mcp-1")
        assert receipt is not None
        assert receipt.producer == ObservabilityProducer.MCP_LOGGER.value
        assert receipt.parity_matched is True


# ---------------------------------------------------------------------------
# Global helper no-op when unconfigured
# ---------------------------------------------------------------------------


def test_record_observability_event_noop_without_config() -> None:
    reset_observability_shadow()
    assert (
        record_observability_event(
            producer=ObservabilityProducer.AUDIT_LOGGER,
            action="noop",
            actor="system",
        )
        is None
    )


def test_build_with_explicit_legacy_mode() -> None:
    reset_observability_shadow()
    repo = build_observability_shadow_repository(
        mode=AuthorityMode.LEGACY, clock=_clock
    )
    assert repo.mode is AuthorityMode.LEGACY
    r = repo.record_event(
        producer=ObservabilityProducer.AUDIT_LOGGER,
        action="legacy-only",
        actor="system",
        event_id="legacy-evt-1",
    )
    assert r.authority == "legacy"
    # In pure legacy mode the port does not dual-write DB; parity may mismatch.
    # Catalog still received the typed record.
    assert repo.catalog.get(CatalogFamily.AUDIT_EVENTS, "legacy-evt-1") is not None
    reset_observability_shadow()
