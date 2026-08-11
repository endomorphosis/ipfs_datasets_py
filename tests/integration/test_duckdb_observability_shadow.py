"""Integration tests for DQK-077 observability shadow routing.

Acceptance coverage:

* Every mutable log/audit/alert record has a typed schema, stable event ID,
  classification, source revision, and parity receipt
* Retries and restarts do not duplicate events
* Secrets and unrestricted SQL are redacted before persistence or publication
* Immutable evidence blobs remain content-addressed outside DuckDB

Producers under test (legacy sinks remain shadow authority):

* ``ipfs_datasets_py.audit.audit_logger``
* ``ipfs_datasets_py.logic.security.audit_log``
* ``ipfs_datasets_py.logic.observability.structured_logging``
* ``ipfs_datasets_py.optimizers.graphrag.audit_logger``
* ``ipfs_datasets_py.optimizers.graphrag.pipeline_json_logger``
* ``ipfs_datasets_py.optimizers.common.logging_audit``
* ``ipfs_datasets_py.alerts.alert_manager``
* ``ipfs_datasets_py.mcp_server.logger``
* ``ipfs_datasets_py.duckdb_control.observability_adapters``
"""

from __future__ import annotations

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

from ipfs_datasets_py.duckdb_control.authority_transition import AuthorityMode
from ipfs_datasets_py.duckdb_control.observability import (
    AUDIT_RECORD_SCHEMA,
    CatalogFamily,
    SensitivityClass,
)
from ipfs_datasets_py.duckdb_control.observability_adapters import (
    ADAPTER_PRODUCERS,
    OBSERVABILITY_ADAPTER_SCHEMA,
    SOURCE_REVISION,
    EmitResult,
    ObservabilityShadowAdapter,
    ProducerKind,
    configure_global_adapter,
    open_shadow_adapter,
    reset_global_adapter,
    stable_event_id,
)


FIXED_CLOCK = "2026-08-11T03:00:00Z"


def _clock() -> str:
    return FIXED_CLOCK


@pytest.fixture
def adapter() -> ObservabilityShadowAdapter:
    reset_global_adapter()
    ad = open_shadow_adapter(memory_legacy=True, clock=_clock)
    configure_global_adapter(ad)
    yield ad
    reset_global_adapter()


# ---------------------------------------------------------------------------
# Adapter core contracts
# ---------------------------------------------------------------------------


def test_adapter_defaults_to_shadow_authority(
    adapter: ObservabilityShadowAdapter,
) -> None:
    assert adapter.mode is AuthorityMode.SHADOW
    assert adapter.source_revision == SOURCE_REVISION
    assert adapter.SCHEMA == OBSERVABILITY_ADAPTER_SCHEMA
    assert adapter.legacy_sink is not None


def test_emit_record_has_typed_schema_stable_id_classification_revision_parity(
    adapter: ObservabilityShadowAdapter,
) -> None:
    result = adapter.emit(
        producer=ProducerKind.AUDIT_LOGGER,
        action="data.read",
        actor="operator",
        outcome="succeeded",
        payload={"resource": "dataset-1", "rows": 12},
        event_id="audit-stable-001",
    )
    assert isinstance(result, EmitResult)
    assert result.event_id == "audit-stable-001"
    assert result.schema == AUDIT_RECORD_SCHEMA
    assert result.classification in {c.value for c in SensitivityClass}
    assert result.source_revision == SOURCE_REVISION
    assert result.parity_receipt_cid.startswith("sha256:")
    assert result.authority_mode == AuthorityMode.SHADOW.value
    assert result.catalog_sequence >= 1
    assert result.matched is True
    assert result.legacy_digest.startswith("sha256:")

    record = adapter.catalog.get(CatalogFamily.AUDIT_EVENTS, "audit-stable-001")
    assert record is not None
    assert record.SCHEMA == AUDIT_RECORD_SCHEMA
    assert record.to_dict()["attributes"]["source_revision"] == SOURCE_REVISION
    assert record.to_dict()["attributes"]["producer"] == ProducerKind.AUDIT_LOGGER.value

    # Legacy sink (authority) received exactly one line.
    assert adapter.legacy_sink.count() == 1
    assert "audit-stable-001" in adapter.legacy_sink.lines()[0]


def test_retries_and_restarts_do_not_duplicate_events(
    adapter: ObservabilityShadowAdapter,
) -> None:
    first = adapter.emit(
        producer=ProducerKind.AUDIT_LOGGER,
        action="retry.safe",
        payload={"n": 1},
        event_id="evt-retry-1",
    )
    second = adapter.emit(
        producer=ProducerKind.AUDIT_LOGGER,
        action="retry.safe",
        payload={"n": 1},
        event_id="evt-retry-1",
    )
    assert first.event_id == second.event_id == "evt-retry-1"
    assert second.idempotent_replay is True
    assert adapter.catalog.counts()["audit_events"] == 1
    assert adapter.legacy_sink.count() == 1

    # Simulate restart: new adapter sharing the same catalog still refuses
    # duplicates via catalog get_by_event_id even with empty in-memory cache.
    restarted = ObservabilityShadowAdapter(
        catalog=adapter.catalog,
        clock=_clock,
    )
    third = restarted.emit(
        producer=ProducerKind.AUDIT_LOGGER,
        action="retry.safe",
        payload={"n": 1},
        event_id="evt-retry-1",
    )
    assert third.idempotent_replay is True
    assert adapter.catalog.counts()["audit_events"] == 1


def test_stable_event_id_is_deterministic() -> None:
    a = stable_event_id(
        producer=ProducerKind.AUDIT_LOGGER,
        action="x",
        body={"k": "v"},
    )
    b = stable_event_id(
        producer=ProducerKind.AUDIT_LOGGER,
        action="x",
        body={"k": "v"},
    )
    c = stable_event_id(
        producer=ProducerKind.AUDIT_LOGGER,
        action="x",
        body={"k": "other"},
    )
    assert a == b
    assert a != c
    assert a.startswith("evt-")


def test_secrets_and_unrestricted_sql_are_redacted(
    adapter: ObservabilityShadowAdapter,
) -> None:
    result = adapter.emit(
        producer=ProducerKind.AUDIT_LOGGER,
        action="query.run",
        payload={
            "password": "s3cret-value",
            "api_key": "sk-live-abcdef",
            "sql": "SELECT * FROM wallets; DROP TABLE accounts;",
            "token": "bearer-xyz",
        },
        event_id="audit-redact-1",
    )
    assert result.classification == SensitivityClass.REDACTED.value

    legacy_blob = "\n".join(adapter.legacy_sink.lines())
    assert "s3cret-value" not in legacy_blob
    assert "sk-live-abcdef" not in legacy_blob
    assert "DROP TABLE" not in legacy_blob
    assert "bearer-xyz" not in legacy_blob
    assert "***REDACTED***" in legacy_blob or "unrestricted_sql" in legacy_blob

    record = adapter.catalog.get(CatalogFamily.AUDIT_EVENTS, "audit-redact-1")
    assert record is not None
    attrs = record.to_dict()["attributes"]
    serialized = str(attrs)
    assert "s3cret-value" not in serialized
    assert "DROP TABLE" not in serialized
    assert record.classification is SensitivityClass.REDACTED


def test_secret_classification_refused(
    adapter: ObservabilityShadowAdapter,
) -> None:
    from ipfs_datasets_py.duckdb_control.observability_adapters import (
        ObservabilityAdapterError,
    )

    with pytest.raises(ObservabilityAdapterError, match="secret"):
        adapter.emit(
            producer=ProducerKind.AUDIT_LOGGER,
            action="forbidden",
            payload={"note": "x"},
            classification=SensitivityClass.SECRET,
            event_id="audit-secret-1",
        )


def test_evidence_blobs_content_addressed_outside_duckdb(
    adapter: ObservabilityShadowAdapter,
) -> None:
    big = {"blob": "x" * 8_000, "kind": "evidence"}
    result = adapter.emit(
        producer=ProducerKind.OPTIMIZER_LOGGING_AUDIT,
        action="evidence.store",
        payload={"label": "big"},
        evidence=big,
        event_id="audit-evidence-1",
    )
    assert result.evidence_cid
    assert result.evidence_cid in adapter.evidence_store
    meta = adapter.evidence_store.meta(result.evidence_cid)
    assert meta is not None
    assert meta.stored_outside_duckdb is True
    assert meta.digest.startswith("sha256:")

    # Catalog only stores the cid reference, not the full blob.
    record = adapter.catalog.get(CatalogFamily.AUDIT_EVENTS, "audit-evidence-1")
    assert record is not None
    attrs = record.to_dict()["attributes"]
    assert attrs.get("evidence_outside_duckdb") is True
    assert attrs.get("evidence_cid") == result.evidence_cid
    assert "x" * 100 not in str(attrs)


def test_all_declared_producers_are_registered() -> None:
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
    assert expected == set(ADAPTER_PRODUCERS)
    assert {k.value for k in ProducerKind} == expected


# ---------------------------------------------------------------------------
# Producer wiring: each expected output routes through the adapter
# ---------------------------------------------------------------------------


def test_audit_logger_producer_routes_shadow(
    adapter: ObservabilityShadowAdapter,
) -> None:
    from ipfs_datasets_py.audit.audit_logger import (
        AuditCategory,
        AuditLevel,
        AuditLogger,
    )

    logger = AuditLogger()
    event_id = logger.log(
        AuditLevel.INFO,
        AuditCategory.SECURITY,
        "login",
        user="alice",
        status="success",
        details={"password": "should-redact", "ip": "10.0.0.1"},
        event_id="prod-audit-001",
    )
    assert event_id == "prod-audit-001"
    record = adapter.catalog.get(CatalogFamily.AUDIT_EVENTS, "prod-audit-001")
    assert record is not None
    assert "should-redact" not in str(record.to_dict())
    assert record.to_dict()["attributes"]["producer"] == ProducerKind.AUDIT_LOGGER.value


def test_logic_security_audit_routes_shadow(
    adapter: ObservabilityShadowAdapter,
) -> None:
    from ipfs_datasets_py.logic.security import audit_log as sec

    before = adapter.catalog.counts()["audit_events"]
    sec.AuditLogger.log_event(
        event_type="proof_attempt",
        user_id="user-1",
        success=True,
        details={"formula": "P -> Q", "password": "nope"},
    )
    after = adapter.catalog.counts()["audit_events"]
    assert after == before + 1
    # Latest record redacted.
    rows = adapter.catalog.list_family(CatalogFamily.AUDIT_EVENTS)
    last = rows[-1]
    assert "nope" not in str(last.to_dict())
    assert last.to_dict()["attributes"]["producer"] == (
        ProducerKind.LOGIC_SECURITY_AUDIT.value
    )


def test_structured_logging_routes_shadow(
    adapter: ObservabilityShadowAdapter,
) -> None:
    from ipfs_datasets_py.logic.observability import structured_logging as sl

    before = adapter.catalog.counts().get("audit_events", 0) + adapter.catalog.counts().get(
        "lifecycle_events", 0
    )
    sl.log_event(
        "system.start",
        component="supervisor",
        event_id="structured-start-1",
    )
    after = adapter.catalog.counts().get("audit_events", 0) + adapter.catalog.counts().get(
        "lifecycle_events", 0
    )
    assert after >= before + 1


def test_graphrag_audit_logger_routes_shadow(
    adapter: ObservabilityShadowAdapter,
) -> None:
    from ipfs_datasets_py.optimizers.graphrag.audit_logger import (
        AuditEvent,
        AuditLogger as GraphAuditLogger,
        EventType,
    )

    logger = GraphAuditLogger(session_id="sess-graph-1", enable_file_logging=False)
    event = AuditEvent.create(
        event_type=EventType.STRATEGY_DECISION,
        round_num=1,
        event_data={"action": "merge_duplicates", "api_key": "secret-key"},
    )
    logger._add_event(event)
    rows = [
        r
        for r in adapter.catalog.list_family(CatalogFamily.AUDIT_EVENTS)
        if r.to_dict()["attributes"].get("producer")
        == ProducerKind.GRAPHRAG_AUDIT.value
    ]
    assert rows
    assert "secret-key" not in str(rows[-1].to_dict())


def test_pipeline_json_logger_routes_shadow(
    adapter: ObservabilityShadowAdapter,
) -> None:
    from ipfs_datasets_py.optimizers.graphrag.pipeline_json_logger import (
        PipelineJSONLogger,
    )

    plog = PipelineJSONLogger(domain="legal")
    plog.start_run(run_id="run-pipe-1", data_source="fixture")
    plog._emit_log(
        "pipeline.stage.started",
        {"stage": "extraction", "password": "hidden"},
    )
    rows = [
        r
        for r in list(adapter.catalog.list_family(CatalogFamily.LIFECYCLE_EVENTS))
        + list(adapter.catalog.list_family(CatalogFamily.AUDIT_EVENTS))
        if r.to_dict().get("attributes", {}).get("producer")
        == ProducerKind.GRAPHRAG_PIPELINE.value
        or (
            hasattr(r, "component")
            and "pipeline" in str(getattr(r, "component", ""))
        )
    ]
    # At least one shadow projection landed.
    assert adapter.catalog.counts()["lifecycle_events"] + adapter.catalog.counts()[
        "audit_events"
    ] >= 1
    blob = str([r.to_dict() for r in adapter.catalog.list_family(CatalogFamily.AUDIT_EVENTS)])
    blob += str(
        [r.to_dict() for r in adapter.catalog.list_family(CatalogFamily.LIFECYCLE_EVENTS)]
    )
    assert "hidden" not in blob


def test_logging_audit_report_routes_shadow(
    adapter: ObservabilityShadowAdapter,
) -> None:
    from ipfs_datasets_py.optimizers.common.logging_audit import (
        LoggingAuditResult,
        LoggingAuditor,
    )

    auditor = LoggingAuditor(root_dir="ipfs_datasets_py/optimizers/common")
    auditor.results = [
        LoggingAuditResult(
            file_path="demo.py",
            class_name="Demo",
            methods_with_logging=["run"],
            methods_without_logging=["generate"],
            has_logger_init=True,
        )
    ]
    report = auditor.generate_report()
    assert "Logging Audit Report" in report
    rows = [
        r
        for r in adapter.catalog.list_family(CatalogFamily.AUDIT_EVENTS)
        if r.to_dict()["attributes"].get("producer")
        == ProducerKind.OPTIMIZER_LOGGING_AUDIT.value
    ]
    assert rows


@pytest.mark.anyio
async def test_alert_manager_routes_shadow(
    adapter: ObservabilityShadowAdapter,
) -> None:
    from ipfs_datasets_py.alerts.alert_manager import AlertManager, AlertRule

    notifier = MagicMock()
    notifier.send_message = AsyncMock(return_value={"ok": True})
    rule = AlertRule(
        rule_id="rule-cpu-high",
        name="CPU high",
        condition={"==": [1, 1]},
        message_template="cpu={cpu} password={password}",
        severity="warning",
    )
    manager = AlertManager(notifier=notifier, rules=[rule])
    # Rule engine may need a simple always-true condition — patch evaluate.
    manager.rule_engine = MagicMock()
    manager.rule_engine.evaluate = MagicMock(return_value=True)

    results = await manager.evaluate_event(
        {"cpu": 99, "password": "alert-secret"}
    )
    assert results
    assert results[0]["status"] == "triggered"
    rows = [
        r
        for r in adapter.catalog.list_family(CatalogFamily.AUDIT_EVENTS)
        if r.to_dict()["attributes"].get("producer")
        == ProducerKind.ALERT_MANAGER.value
    ]
    assert rows
    assert "alert-secret" not in str(rows[-1].to_dict())


def test_mcp_logger_routes_shadow(
    adapter: ObservabilityShadowAdapter,
) -> None:
    # Re-import to ensure handler is attached; adapter is process-global.
    from ipfs_datasets_py.mcp_server import logger as mcp_logger_mod

    before = adapter.catalog.counts()["audit_events"]
    mcp_logger_mod.logger.info(
        "MCP tool completed with token=should-not-persist-as-secret-value"
    )
    after = adapter.catalog.counts()["audit_events"]
    # Handler may redact token assignments; at least one event projected.
    assert after >= before + 1
    rows = [
        r
        for r in adapter.catalog.list_family(CatalogFamily.AUDIT_EVENTS)
        if r.to_dict()["attributes"].get("producer")
        == ProducerKind.MCP_LOGGER.value
    ]
    assert rows


def test_shadow_authority_is_legacy_not_catalog(
    adapter: ObservabilityShadowAdapter,
) -> None:
    """Legacy file sink is authority; catalog is projection (mode=shadow)."""

    result = adapter.emit(
        producer=ProducerKind.AUDIT_LOGGER,
        action="authority.check",
        event_id="auth-check-1",
        payload={"ok": True},
    )
    assert result.authority_mode == "shadow"
    # Authority port read returns legacy payload.
    legacy = adapter.authority.read("auth-check-1")
    assert legacy is not None
    assert legacy["event_id"] == "auth-check-1"
    assert legacy["source_revision"] == SOURCE_REVISION
    # Parity matched between legacy and db projection.
    assert result.matched is True
    assert result.parity_receipt_cid


def test_module_import_is_inert() -> None:
    """Importing observability_adapters must not require duckdb I/O."""

    import importlib

    import builtins

    real_import = builtins.__import__

    def guarded(name: str, *args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        root = name.split(".", 1)[0]
        if root in {"duckdb", "pyarrow", "fsspec"}:
            raise AssertionError(f"unexpected import of {name!r} at load time")
        return real_import(name, *args, **kwargs)

    for key in list(sys.modules):
        if key == "ipfs_datasets_py.duckdb_control.observability_adapters" or key.startswith(
            "ipfs_datasets_py.duckdb_control.observability_adapters."
        ):
            del sys.modules[key]

    builtins.__import__ = guarded  # type: ignore[assignment]
    try:
        mod = importlib.import_module(
            "ipfs_datasets_py.duckdb_control.observability_adapters"
        )
        assert mod.OBSERVABILITY_ADAPTER_SCHEMA.endswith("@1")
    finally:
        builtins.__import__ = real_import  # type: ignore[assignment]
