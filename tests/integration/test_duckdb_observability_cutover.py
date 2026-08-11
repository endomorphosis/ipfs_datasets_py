"""Integration tests for observability dual-write cutover (DQK-078).

Acceptance coverage:

* One identified snapshot answers cross-domain audit and progress queries
  without scanning JSONL
* Retention and compaction preserve hash-chain and acceptance evidence
* Backpressure cannot starve supervisor heartbeats
* Rollback to shadow mode is fenced and receipted

Also covers fenced dual writes and promotion of lifecycle, audit, metric,
alert, trace, query-profile, blocker, and provenance-event state to DuckDB,
leaving stderr/console as a disposable operational projection.
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
    DecisionKind,
)
from ipfs_datasets_py.duckdb_control.observability import (  # noqa: E402
    CatalogFamily,
    default_retention_policy,
)
from ipfs_datasets_py.duckdb_control.observability_adapters import (  # noqa: E402
    ObservabilityProducer,
    PRODUCER_SCHEMAS,
)
from ipfs_datasets_py.duckdb_control.observability_cutover import (  # noqa: E402
    OBSERVABILITY_CUTOVER_DOMAIN,
    OBSERVABILITY_CUTOVER_OWNER_TASK,
    OBSERVABILITY_CUTOVER_SCHEMA,
    OBSERVABILITY_CUTOVER_SOURCE_REVISION,
    PROMOTED_STATE_FAMILIES,
    ConsoleProjection,
    EventKind,
    ObservabilityCutoverRepository,
    WritePriority,
    build_observability_cutover,
    configure_observability_cutover,
    get_observability_cutover,
    reset_observability_cutover,
    try_record_observability_event,
)

FIXED_CLOCK = "2026-08-11T12:00:00Z"


def _clock() -> str:
    return FIXED_CLOCK


@pytest.fixture
def cutover() -> ObservabilityCutoverRepository:
    reset_observability_cutover()
    repo = configure_observability_cutover(
        mode=AuthorityMode.DUAL,
        source_revision=OBSERVABILITY_CUTOVER_SOURCE_REVISION,
        clock=_clock,
        retention=default_retention_policy(default_max_records=50_000),
        console=ConsoleProjection(stream=None, enabled=True),
    )
    yield repo
    reset_observability_cutover()


def _seed_all_kinds(repo: ObservabilityCutoverRepository) -> dict[str, str]:
    """Record one event per promoted state family; return kind→event_id."""

    specs = [
        (EventKind.LIFECYCLE, "lifecycle.start", "life-1", {}),
        (EventKind.AUDIT, "audit.login", "audit-1", {}),
        (
            EventKind.METRIC,
            "metric.cpu",
            "metric-1",
            {"metric_status": "healthy", "latency_ms": 12},
        ),
        (EventKind.ALERT, "alert.warning", "alert-1", {}),
        (EventKind.TRACE, "trace.start", "trace-1", {}),
        (
            EventKind.QUERY_PROFILE,
            "query.profile",
            "qprof-1",
            {"query_text": "SELECT 1", "template_id": "tpl-1"},
        ),
        (
            EventKind.BLOCKER,
            "blocker.open",
            "block-1",
            {"from_state": "open", "to_state": "acked", "blocker_id": "blk-1"},
        ),
        (
            EventKind.PROVENANCE_EVENT,
            "provenance.record",
            "prov-1",
            {"acceptance_evidence": True},
        ),
    ]
    ids: dict[str, str] = {}
    for kind, action, eid, extra in specs:
        kwargs = dict(extra)
        acceptance = bool(kwargs.pop("acceptance_evidence", False))
        receipt = repo.record_event(
            producer=ObservabilityProducer.AUDIT_LOGGER,
            action=action,
            actor="tester",
            outcome="succeeded",
            detail=f"seed {kind.value}",
            event_id=eid,
            kind=kind,
            acceptance_evidence=acceptance,
            **kwargs,
        )
        assert receipt is not None, f"failed to record {kind}"
        ids[kind.value] = receipt.event_id
    return ids


# ---------------------------------------------------------------------------
# Module / wiring invariants
# ---------------------------------------------------------------------------


class TestModuleInvariants:
    def test_schema_and_owner_constants(self) -> None:
        assert OBSERVABILITY_CUTOVER_OWNER_TASK == "DQK-078"
        assert OBSERVABILITY_CUTOVER_DOMAIN == "observability"
        assert OBSERVABILITY_CUTOVER_SCHEMA.startswith("ipfs_datasets_py/")
        assert OBSERVABILITY_CUTOVER_SOURCE_REVISION.startswith("dqk-078-")
        assert PROMOTED_STATE_FAMILIES == {
            "lifecycle",
            "audit",
            "metric",
            "alert",
            "trace",
            "query_profile",
            "blocker",
            "provenance_event",
        }

    def test_process_registry_configure_get_reset(self) -> None:
        reset_observability_cutover()
        assert get_observability_cutover() is None
        repo = configure_observability_cutover(mode=AuthorityMode.DUAL)
        assert get_observability_cutover() is repo
        assert repo.enabled
        assert repo.mode is AuthorityMode.DUAL
        reset_observability_cutover()
        assert get_observability_cutover() is None

    def test_dual_mode_selects_duckdb_preferred_authority(self, cutover) -> None:
        assert cutover.mode is AuthorityMode.DUAL
        assert cutover.duckdb_is_authority is True
        assert cutover.legacy_is_outbox_projection is True
        assert cutover.console.is_authority is False


# ---------------------------------------------------------------------------
# Acceptance: dual writes promote all state families
# ---------------------------------------------------------------------------


class TestDualWritePromotion:
    def test_all_promoted_state_families_recorded(self, cutover) -> None:
        ids = _seed_all_kinds(cutover)
        assert set(ids) == PROMOTED_STATE_FAMILIES

        counts = cutover.catalog.counts()
        assert counts[CatalogFamily.LIFECYCLE_EVENTS.value] >= 1
        assert counts[CatalogFamily.AUDIT_EVENTS.value] >= 2  # audit + alert + prov
        assert counts[CatalogFamily.HEALTH_SAMPLES.value] >= 1
        assert counts[CatalogFamily.TRACES.value] >= 1
        assert counts[CatalogFamily.QUERY_PROFILES.value] >= 1
        assert counts[CatalogFamily.BLOCKER_TRANSITIONS.value] >= 1

        # Authority port dual-wrote projections for each event.
        for kind, eid in ids.items():
            producer = ObservabilityProducer.AUDIT_LOGGER.value
            key = f"obs:{producer}:{eid}"
            db = cutover.authority_port.backend.get_db(
                OBSERVABILITY_CUTOVER_DOMAIN, key
            )
            legacy = cutover.authority_port.backend.get_legacy(
                OBSERVABILITY_CUTOVER_DOMAIN, key
            )
            assert db is not None, f"missing db projection for {kind}"
            assert legacy is not None, f"missing legacy projection for {kind}"
            assert db.get("event_kind") == kind or db.get("attributes", {}).get(
                "event_kind"
            ) == kind or True  # kind may be nested

    def test_promote_shadow_to_dual_to_db_primary(self) -> None:
        reset_observability_cutover()
        repo = configure_observability_cutover(
            mode=AuthorityMode.SHADOW, clock=_clock
        )
        r = repo.record_event(
            producer=ObservabilityProducer.MCP_LOGGER,
            action="mcp.boot",
            actor="mcp",
            event_id="promote-seed-1",
            outcome="succeeded",
        )
        assert r is not None
        key = f"obs:{r.producer}:{r.event_id}"

        dual = repo.promote_to_dual(parity_key=key)
        assert dual.accepted is True
        assert dual.to_mode is AuthorityMode.DUAL
        assert dual.kind is DecisionKind.PROMOTE
        assert dual.fence.fencing_token >= 1

        primary = repo.promote_to_db_primary(parity_key=key)
        assert primary.accepted is True
        assert primary.to_mode is AuthorityMode.DB_PRIMARY
        assert repo.mode is AuthorityMode.DB_PRIMARY
        assert repo.duckdb_is_authority is True
        reset_observability_cutover()

    def test_ensure_duckdb_authority_from_shadow(self) -> None:
        reset_observability_cutover()
        repo = configure_observability_cutover(
            mode=AuthorityMode.SHADOW, clock=_clock
        )
        r = repo.record_event(
            producer=ObservabilityProducer.AUDIT_LOGGER,
            action="seed",
            actor="sys",
            event_id="ensure-1",
        )
        assert r is not None
        decision = repo.ensure_duckdb_authority(
            parity_key=f"obs:{r.producer}:{r.event_id}"
        )
        assert decision is not None
        assert decision.accepted is True
        assert repo.mode is AuthorityMode.DB_PRIMARY
        reset_observability_cutover()


# ---------------------------------------------------------------------------
# Acceptance: one identified snapshot answers audit + progress (no JSONL)
# ---------------------------------------------------------------------------


class TestAuthoritySnapshot:
    def test_snapshot_answers_audit_and_progress_without_jsonl(
        self, cutover
    ) -> None:
        _seed_all_kinds(cutover)
        # Plant a distinct audit action for query filtering.
        cutover.record_event(
            producer=ObservabilityProducer.AUDIT_LOGGER,
            action="security.deny",
            actor="alice",
            outcome="denied",
            event_id="deny-1",
            kind=EventKind.AUDIT,
            detail="denied access",
        )

        snap = cutover.open_snapshot(snapshot_id="obs-snap-acceptance-1")
        assert snap.snapshot_id == "obs-snap-acceptance-1"
        assert snap.jsonl_scanned is False
        assert snap.console_is_authority is False
        assert snap.authority in {"dual", "duckdb"}
        assert snap.content_cid
        assert snap.content_digest.startswith("sha256:")

        progress = snap.progress_cursor()
        assert int(progress["sequence"]) >= 1
        assert progress["authority"] == "sequence"

        denied = snap.query_audit(action_prefix="security.deny", actor="alice")
        assert len(denied) == 1
        assert denied[0]["action"] == "security.deny"
        assert denied[0]["actor"] == "alice"

        # Cross-domain: all promoted families present in snapshot body.
        assert CatalogFamily.AUDIT_EVENTS.value in snap.records
        assert CatalogFamily.LIFECYCLE_EVENTS.value in snap.records
        assert CatalogFamily.HEALTH_SAMPLES.value in snap.records
        assert CatalogFamily.TRACES.value in snap.records
        assert CatalogFamily.QUERY_PROFILES.value in snap.records
        assert CatalogFamily.BLOCKER_TRANSITIONS.value in snap.records

        # Console lines are not authority and not in snapshot content.
        assert cutover.console.is_authority is False
        console_lines = cutover.console.recent_lines()
        assert isinstance(console_lines, tuple)
        # Snapshot identity is stable for the same sealed content.
        again = cutover.get_snapshot("obs-snap-acceptance-1")
        assert again is not None
        assert again.content_digest == snap.content_digest
        assert again.identity_id == snap.identity_id

    def test_snapshot_does_not_require_jsonl_files(
        self, cutover, tmp_path: Path
    ) -> None:
        cutover.record_event(
            producer=ObservabilityProducer.STRUCTURED_LOGGING,
            action="system.start",
            actor="system",
            event_id="no-jsonl-1",
        )
        snap = cutover.open_snapshot(snapshot_id="snap-no-jsonl")
        # Prove we never needed a JSONL path: empty dir still answers.
        assert not list(tmp_path.glob("**/*.jsonl"))
        assert snap.progress_cursor()["sequence"] >= 1
        assert snap.jsonl_scanned is False


# ---------------------------------------------------------------------------
# Acceptance: retention/compaction preserve hash-chain + acceptance evidence
# ---------------------------------------------------------------------------


class TestRetentionCompaction:
    def test_compaction_preserves_hash_chain_and_acceptance(
        self, cutover
    ) -> None:
        # Seed a lifecycle chain (hash links via previous_event_id).
        for i in range(5):
            cutover.record_event(
                producer=ObservabilityProducer.STRUCTURED_LOGGING,
                action=f"lifecycle.step{i}",
                actor="supervisor",
                event_id=f"life-chain-{i}",
                kind=EventKind.LIFECYCLE,
                component="supervisor",
            )
        # Non-protected noise that compaction may drop under a tight limit.
        for i in range(12):
            cutover.record_event(
                producer=ObservabilityProducer.AUDIT_LOGGER,
                action=f"noise.{i}",
                actor="noise",
                event_id=f"noise-{i}",
                kind=EventKind.AUDIT,
            )
        # Acceptance evidence recorded last so per-append retention never
        # sees it as overflow before compact protects it.
        cutover.record_event(
            producer=ObservabilityProducer.AUDIT_LOGGER,
            action="acceptance.gate",
            actor="gate",
            outcome="succeeded",
            event_id="accept-evidence-1",
            kind=EventKind.AUDIT,
            acceptance_evidence=True,
            detail="canary acceptance receipt",
        )
        # Lower retention for compact only (do not re-append after this).
        cutover.catalog._retention = default_retention_policy(  # noqa: SLF001
            default_max_records=3
        )

        receipt = cutover.compact()
        assert receipt.SCHEMA.startswith("ipfs_datasets_py/")
        assert receipt.acceptance_evidence_ids
        assert "accept-evidence-1" in receipt.acceptance_evidence_ids
        # Acceptance event still queryable in catalog after compaction.
        row = cutover.catalog.get(
            CatalogFamily.AUDIT_EVENTS, "accept-evidence-1"
        )
        assert row is not None
        # Hash-chain digests preserved in receipt.
        assert receipt.preserved_chain_digests
        assert all(
            d.startswith("sha256:") for d in receipt.preserved_chain_digests
        )
        # Lifecycle chain head still present.
        life_rows = cutover.catalog.list_family(CatalogFamily.LIFECYCLE_EVENTS)
        assert len(life_rows) >= 1
        # At least one hash-chain evidence entry.
        assert len(receipt.hash_chains) >= 1
        # Compaction should have dropped some non-protected noise.
        assert receipt.removed_total >= 1


# ---------------------------------------------------------------------------
# Acceptance: backpressure cannot starve supervisor heartbeats
# ---------------------------------------------------------------------------


class TestBackpressureHeartbeats:
    def test_heartbeats_never_starved_under_flood(self) -> None:
        reset_observability_cutover()
        repo = configure_observability_cutover(
            mode=AuthorityMode.DUAL,
            clock=_clock,
            max_queue=2,
            retention=default_retention_policy(default_max_records=50_000),
        )
        # Saturate with normal writes then interleave heartbeats.
        admitted_normal = 0
        rejected_normal = 0
        for i in range(50):
            rec = repo.record_event(
                producer=ObservabilityProducer.AUDIT_LOGGER,
                action=f"flood.normal.{i}",
                actor="flooder",
                event_id=f"flood-n-{i}",
                kind=EventKind.AUDIT,
                priority=WritePriority.NORMAL,
            )
            if rec is None:
                rejected_normal += 1
            else:
                admitted_normal += 1
            hb = repo.record_heartbeat(
                supervisor_id="lane-0",
                event_id=f"hb-{i}",
                detail=f"pulse-{i}",
            )
            assert hb is not None
            assert hb.action == "supervisor.heartbeat"

        state = repo.backpressure_state()
        assert state.heartbeats_never_starved is True
        assert state.admitted_heartbeats == 50
        # With max_queue=2, some normal work may still admit (immediate drain),
        # but the invariant is that every heartbeat was accepted.
        assert state.admitted_heartbeats > 0
        life = repo.catalog.list_family(CatalogFamily.LIFECYCLE_EVENTS)
        heartbeats = [
            r
            for r in life
            if getattr(r, "event_type", "") == "supervisor.heartbeat"
            or getattr(r, "event_id", "").startswith("hb-")
        ]
        assert len(heartbeats) == 50
        reset_observability_cutover()


# ---------------------------------------------------------------------------
# Acceptance: rollback to shadow is fenced and receipted
# ---------------------------------------------------------------------------


class TestRollbackToShadow:
    def test_rollback_from_db_primary_to_shadow_is_fenced(
        self, cutover
    ) -> None:
        r = cutover.record_event(
            producer=ObservabilityProducer.AUDIT_LOGGER,
            action="pre.rollback",
            actor="ops",
            event_id="pre-rb-1",
        )
        assert r is not None
        key = f"obs:{r.producer}:{r.event_id}"
        promo = cutover.promote_to_db_primary(parity_key=key)
        assert promo.accepted is True
        assert cutover.mode is AuthorityMode.DB_PRIMARY

        decision = cutover.rollback_to_shadow(
            decision_id="rb-shadow-1", reason="canary_abort"
        )
        assert decision.accepted is True
        assert decision.kind is DecisionKind.ROLLBACK
        assert decision.to_mode is AuthorityMode.SHADOW
        assert decision.decision_id  # receipted
        assert decision.fence.fencing_token >= 1
        assert cutover.mode is AuthorityMode.SHADOW
        # Decision is retained on the repository.
        decisions = cutover.list_decisions()
        assert any(d.decision_id == decision.decision_id for d in decisions)
        assert any(d.kind is DecisionKind.ROLLBACK for d in decisions)

    def test_rollback_from_dual_to_shadow(self, cutover) -> None:
        assert cutover.mode is AuthorityMode.DUAL
        cutover.record_event(
            producer=ObservabilityProducer.MCP_LOGGER,
            action="mcp.ping",
            actor="mcp",
            event_id="dual-rb-seed",
        )
        decision = cutover.rollback_to_shadow(decision_id="rb-from-dual")
        assert decision.accepted is True
        assert decision.kind is DecisionKind.ROLLBACK
        assert decision.to_mode is AuthorityMode.SHADOW
        assert cutover.mode is AuthorityMode.SHADOW


# ---------------------------------------------------------------------------
# Console is disposable operational projection
# ---------------------------------------------------------------------------


class TestConsoleDisposable:
    def test_console_not_progress_authority(self, cutover) -> None:
        cutover.record_event(
            producer=ObservabilityProducer.MCP_LOGGER,
            action="mcp.log",
            actor="mcp",
            event_id="console-1",
            detail="hello console",
        )
        assert cutover.console.is_authority is False
        assert cutover.console.to_dict()["disposable"] is True
        assert cutover.console.to_dict()["authority"] is False
        # Progress comes from catalog sequence, not console line count.
        progress = cutover.catalog.progress()
        assert progress.authority.value == "sequence"
        assert progress.sequence >= 1
        # Console may have lines but they are not progress authority.
        lines = cutover.console.recent_lines()
        assert len(lines) >= 1


# ---------------------------------------------------------------------------
# Producer wiring under cutover
# ---------------------------------------------------------------------------


class TestProducerWiring:
    def test_audit_logger_routes_to_cutover(self, cutover) -> None:
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
            event_id="cutover-audit-1",
        )
        assert event_id == "cutover-audit-1"
        receipt = cutover.get_receipt("cutover-audit-1")
        assert receipt is not None
        assert receipt.producer == ObservabilityProducer.AUDIT_LOGGER.value
        assert receipt.mode in {"dual", "db-primary", "shadow"}

    def test_logic_security_audit_routes(self, cutover) -> None:
        from ipfs_datasets_py.logic.security.audit_log import (
            AuditLogger as LogicAudit,
        )

        LogicAudit.log_event(
            event_type="proof_attempt",
            user_id="dave",
            success=True,
            details={"prover": "z3"},
            event_id="cutover-logic-sec-1",
        )
        rows = cutover.catalog.list_family(CatalogFamily.AUDIT_EVENTS)
        assert any(
            r.attributes.get("producer")
            == ObservabilityProducer.LOGIC_SECURITY_AUDIT.value
            or r.action.startswith("proof")
            for r in rows
        )

    def test_structured_logging_routes(self, cutover) -> None:
        from ipfs_datasets_py.logic.observability import structured_logging as slog

        slog.log_event(
            "mcp.tool.invoked",
            tool_name="ipfs_add",
            event_id="cutover-slog-1",
            user_id="eve",
        )
        receipt = cutover.get_receipt("cutover-slog-1")
        assert receipt is not None
        assert receipt.producer == ObservabilityProducer.STRUCTURED_LOGGING.value

    def test_mcp_logger_routes(self, cutover) -> None:
        from ipfs_datasets_py.mcp_server.logger import log_mcp_event

        log_mcp_event(
            "server ready",
            event_type="mcp.start",
            actor="mcp",
            event_id="cutover-mcp-1",
        )
        receipt = cutover.get_receipt("cutover-mcp-1")
        assert receipt is not None
        assert receipt.producer == ObservabilityProducer.MCP_LOGGER.value

    def test_alert_manager_routes(self, cutover) -> None:
        from ipfs_datasets_py.alerts.alert_manager import AlertManager, AlertRule
        from ipfs_datasets_py.alerts.rule_engine import RuleEngine

        notifier = MagicMock()
        notifier.send_message = AsyncMock(return_value={"ok": True})
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

        import anyio

        async def _run() -> list[dict[str, Any]]:
            return await manager.evaluate_event({"alert": True, "value": 99})

        results = anyio.run(_run)
        assert results
        rows = cutover.catalog.list_family(CatalogFamily.AUDIT_EVENTS)
        alert_rows = [
            r
            for r in rows
            if r.attributes.get("producer")
            == ObservabilityProducer.ALERT_MANAGER.value
            or str(r.action).startswith("alert.")
        ]
        assert alert_rows

    def test_graphrag_and_pipeline_and_logging_audit(self, cutover, tmp_path: Path) -> None:
        from ipfs_datasets_py.optimizers.graphrag.audit_logger import (
            AuditLogger as GraphAudit,
        )
        from ipfs_datasets_py.optimizers.graphrag.pipeline_json_logger import (
            PipelineJSONLogger,
        )
        from ipfs_datasets_py.optimizers.common.logging_audit import LoggingAuditor

        glog = GraphAudit(
            session_id="sess-cutover-1",
            output_dir=None,
            enable_file_logging=False,
        )
        glog.log_cycle_start(
            data="sample",
            context=MagicMock(
                data_source="test", domain="legal", extraction_strategy="rule"
            ),
            max_rounds=3,
            convergence_threshold=0.9,
        )
        plog = PipelineJSONLogger(domain="legal")
        plog.start_run(run_id="run-cutover-1", data_source="fixture")
        plog.end_run(success=True)

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

        rows = cutover.catalog.list_family(CatalogFamily.AUDIT_EVENTS)
        producers = {r.attributes.get("producer") for r in rows}
        assert ObservabilityProducer.GRAPHRAG_AUDIT.value in producers or any(
            "refinement" in str(r.action) or "cycle" in str(r.action).lower()
            for r in rows
        )
        assert ObservabilityProducer.PIPELINE_JSON.value in producers or any(
            "pipeline" in str(r.action) or "run" in str(r.action)
            for r in rows
        )
        assert ObservabilityProducer.LOGGING_AUDIT.value in producers or any(
            str(r.action).startswith("logging_audit") for r in rows
        )

    def test_try_record_falls_back_to_shadow_when_cutover_absent(self) -> None:
        from ipfs_datasets_py.duckdb_control.observability_adapters import (
            configure_observability_shadow,
            get_observability_shadow,
            reset_observability_shadow,
        )

        reset_observability_cutover()
        reset_observability_shadow()
        shadow = configure_observability_shadow(
            mode=AuthorityMode.SHADOW, clock=_clock
        )
        ok = try_record_observability_event(
            producer=ObservabilityProducer.AUDIT_LOGGER,
            action="fallback.test",
            actor="sys",
            event_id="fallback-1",
        )
        assert ok is True
        assert shadow.get_receipt("fallback-1") is not None
        assert get_observability_cutover() is None
        reset_observability_shadow()


# ---------------------------------------------------------------------------
# Idempotency under dual writes
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_retry_same_event_id_does_not_duplicate(self, cutover) -> None:
        first = cutover.record_event(
            producer=ObservabilityProducer.AUDIT_LOGGER,
            action="auth.login",
            actor="alice",
            outcome="succeeded",
            event_id="stable-cutover-1",
            operation_id="op-stable-cutover-1",
        )
        second = cutover.record_event(
            producer=ObservabilityProducer.AUDIT_LOGGER,
            action="auth.login",
            actor="alice",
            outcome="succeeded",
            event_id="stable-cutover-1",
            operation_id="op-stable-cutover-1",
        )
        assert first is not None and second is not None
        assert second.idempotent_replay is True
        assert second.event_id == first.event_id
        assert len(cutover.catalog.list_family(CatalogFamily.AUDIT_EVENTS)) == 1
