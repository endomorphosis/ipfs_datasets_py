"""E2E: DuckDB-only observability after mutable file-sink removal (DQK-079).

Acceptance coverage:

* Runtime succeeds with legacy audit/log/metric JSON files absent
* Static and dynamic writer guards reject undeclared mutable file sinks
* Console logs cannot satisfy progress or completion authority
* Sanitized publication views exclude secrets and high-cardinality private payloads
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

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

from ipfs_datasets_py.audit.audit_logger import (  # noqa: E402
    AuditCategory,
    AuditLevel,
    AuditLogger,
)
from ipfs_datasets_py.duckdb_control.authority_transition import (  # noqa: E402
    AuthorityMode,
)
from ipfs_datasets_py.duckdb_control.observability_adapters import (  # noqa: E402
    ObservabilityProducer,
)
from ipfs_datasets_py.duckdb_control.observability_cutover import (  # noqa: E402
    ConsoleProjection,
    EventKind,
    configure_observability_cutover,
    get_observability_cutover,
    reset_observability_cutover,
    try_record_observability_event,
)
from ipfs_datasets_py.logic.observability.structured_logging import (  # noqa: E402
    HIGH_CARDINALITY_PRIVATE_KEYS,
    LEGACY_MUTABLE_OBSERVABILITY_FILENAMES,
    OBSERVABILITY_FILE_SINK_OWNER_TASK,
    OBSERVABILITY_PRODUCER_MODULE_PATHS,
    ObservabilityConsoleAuthorityError,
    ObservabilityMutableFileSinkError,
    assert_console_not_progress_or_completion_authority,
    assert_handler_not_undeclared_file_sink,
    assert_mutable_file_sink_allowed,
    duckdb_is_observability_authority,
    get_logger,
    legacy_mutable_file_sinks_allowed,
    log_event,
    permit_explicit_observability_export,
    sanitized_publication_view,
    static_guard_observability_producers,
    static_guard_reject_undeclared_file_sinks,
)
from ipfs_datasets_py.logic.security import audit_log as logic_audit  # noqa: E402
from ipfs_datasets_py.mcp_server import logger as mcp_logger_mod  # noqa: E402
from ipfs_datasets_py.optimizers.common.logging_audit import (  # noqa: E402
    LoggingAuditor,
    export_report,
)
from ipfs_datasets_py.optimizers.graphrag.audit_logger import (  # noqa: E402
    AuditLogger as GraphAuditLogger,
    create_audit_logger,
)
from ipfs_datasets_py.optimizers.graphrag.pipeline_json_logger import (  # noqa: E402
    PipelineJSONLogger,
)
from ipfs_datasets_py.alerts.alert_manager import (  # noqa: E402
    AlertManager,
    AlertRule,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def export_only():
    """Post-canary export-only observability cutover (DQK-079)."""
    reset_observability_cutover()
    repo = configure_observability_cutover(
        mode=AuthorityMode.EXPORT_ONLY,
        console=ConsoleProjection(stream=None, enabled=True),
    )
    yield repo
    reset_observability_cutover()


@pytest.fixture
def db_primary():
    """Post-canary db-primary observability cutover (DQK-079)."""
    reset_observability_cutover()
    repo = configure_observability_cutover(
        mode=AuthorityMode.DB_PRIMARY,
        console=ConsoleProjection(stream=None, enabled=True),
    )
    yield repo
    reset_observability_cutover()


@pytest.fixture
def empty_legacy_root(tmp_path):
    root = tmp_path / "no-legacy-obs"
    root.mkdir()
    for name in LEGACY_MUTABLE_OBSERVABILITY_FILENAMES:
        assert not (root / name).exists()
    return root


class _FakeNotifier:
    async def send_message(self, **kwargs):
        return {"ok": True, "kwargs": kwargs}


# ---------------------------------------------------------------------------
# Runtime without legacy files
# ---------------------------------------------------------------------------


def test_runtime_without_legacy_json_files(db_primary, empty_legacy_root):
    """Producers succeed with every legacy audit/log/metric JSON file absent."""

    assert duckdb_is_observability_authority() is True
    assert legacy_mutable_file_sinks_allowed() is False

    # Core audit logger — in-memory only
    AuditLogger._instance = None
    al = AuditLogger.get_instance()
    eid = al.info(
        AuditCategory.SECURITY,
        "dqk079.e2e",
        user="tester",
        details={"message": "no files"},
    )
    assert eid
    assert al._events

    # Logic security audit with requested path — must not create the file
    target = empty_legacy_root / "audit_log.json"
    logic_audit.AuditLogger(log_path=str(target))
    logic_audit.AuditLogger.log_event(
        event_type="e2e.probe",
        user_id="tester",
        success=True,
        details={"message": "console only"},
    )
    assert not target.exists()

    # GraphRAG audit — file logging forced off
    gal = GraphAuditLogger(
        output_dir=str(empty_legacy_root / "audit_logs"),
        enable_file_logging=True,
    )
    assert gal.enable_file_logging is False
    gal.log_cycle_start(
        data="e2e",
        context=type(
            "C",
            (),
            {
                "data_source": "e2e",
                "domain": "test",
                "extraction_strategy": "x",
            },
        )(),
        max_rounds=1,
        convergence_threshold=0.5,
    )
    assert gal.events
    assert not list((empty_legacy_root / "audit_logs").glob("*.jsonl")) if (
        empty_legacy_root / "audit_logs"
    ).exists() else True

    # Pipeline JSON logger
    plog = PipelineJSONLogger(domain="e2e")
    plog._emit_log("e2e.pipeline", {"status": "ok"})

    # MCP logger
    mcp_logger_mod.log_mcp_event("e2e probe", event_type="mcp.e2e")

    # Structured logging
    slog = get_logger("e2e.obs", use_json=True)
    slog.info("structured console only")
    log_event("e2e.event", component="e2e")

    # Logging auditor report is console-only
    auditor = LoggingAuditor(root_dir=str(_REPO_ROOT / "ipfs_datasets_py" / "optimizers" / "common"))
    # Limit scan to avoid long runtime
    auditor.root_dir = _REPO_ROOT / "ipfs_datasets_py" / "optimizers" / "common"
    auditor.results = []
    for py in list(auditor.root_dir.glob("*.py"))[:3]:
        auditor.results.append(auditor.audit_file(py))
    report = auditor.generate_report()
    assert "Logging Audit Report" in report or "Scanned" in report

    # Alert manager in-memory rules (no alert_state.json)
    mgr = AlertManager(notifier=_FakeNotifier(), rules=[
        AlertRule(
            rule_id="r1",
            name="probe",
            condition={"==": [1, 1]},
            message_template="hello",
            severity="info",
        )
    ])
    assert mgr.list_rules()

    for name in LEGACY_MUTABLE_OBSERVABILITY_FILENAMES:
        assert not (empty_legacy_root / name).exists()


def test_export_only_rejects_authority_writes_but_runtime_ok(export_only, empty_legacy_root):
    assert export_only.mode is AuthorityMode.EXPORT_ONLY
    assert export_only.duckdb_is_authority is True
    assert export_only.console.is_authority is False

    # Snapshot still answers without JSONL (empty catalog is fine).
    snap = export_only.open_snapshot()
    assert snap.jsonl_scanned is False
    assert snap.console_is_authority is False
    assert snap.authority == "duckdb"

    # Producers still emit console lines without creating files.
    create_audit_logger(output_dir=str(empty_legacy_root / "g"), enable_file_logging=True)
    for name in LEGACY_MUTABLE_OBSERVABILITY_FILENAMES:
        assert not (empty_legacy_root / name).exists()


# ---------------------------------------------------------------------------
# Static + dynamic writer guards
# ---------------------------------------------------------------------------


def test_static_guards_reject_unguarded_file_sinks():
    bad = '''
import json
from pathlib import Path

def save_metric_snapshot(path):
    with open(path, "w") as f:
        json.dump({"cpu": 1}, f)
'''
    hits = static_guard_reject_undeclared_file_sinks(bad, path="evil.py")
    assert hits, "expected static guard violations for unguarded json.dump"

    good = '''
from ipfs_datasets_py.logic.observability.structured_logging import (
    permit_explicit_observability_export,
    assert_mutable_file_sink_allowed,
)
import json

def export_json(path):
    with permit_explicit_observability_export():
        assert_mutable_file_sink_allowed(path, kind="export", explicit_export=True)
        with open(path, "w") as f:
            json.dump({"ok": True}, f)
'''
    hits_good = static_guard_reject_undeclared_file_sinks(good, path="good.py")
    assert hits_good == []


def test_static_guards_pass_on_producer_modules():
    report = static_guard_observability_producers(repo_root=_REPO_ROOT)
    assert set(report) == set(OBSERVABILITY_PRODUCER_MODULE_PATHS)
    violations = {k: v for k, v in report.items() if v}
    assert not violations, f"static guard violations: {violations}"


def test_dynamic_guard_rejects_undeclared_file_sinks(export_only, tmp_path):
    assert legacy_mutable_file_sinks_allowed() is False

    with pytest.raises(ObservabilityMutableFileSinkError):
        assert_mutable_file_sink_allowed(tmp_path / "audit.jsonl", kind="audit")

    with pytest.raises(ObservabilityMutableFileSinkError):
        assert_mutable_file_sink_allowed(
            tmp_path / "metric_snapshot.json", kind="metric_snapshot"
        )

    with pytest.raises(ObservabilityMutableFileSinkError):
        assert_mutable_file_sink_allowed(
            tmp_path / "alert_state.json", kind="alert_state"
        )

    # Core audit logger rejects file-backed handlers
    class _Fileish:
        name = "fileish"
        file_path = str(tmp_path / "audit.json")

        def handle(self, event):
            return True

        def close(self):
            return None

    AuditLogger._instance = None
    al = AuditLogger()
    with pytest.raises(ObservabilityMutableFileSinkError):
        al.add_handler(_Fileish())  # type: ignore[arg-type]

    # get_logger rejects FileHandler
    fh_path = tmp_path / "structured.jsonl"
    fh = logging.FileHandler(fh_path)
    try:
        with pytest.raises(ObservabilityMutableFileSinkError):
            get_logger("e2e.file", handlers=[fh])
    finally:
        fh.close()

    # GraphRAG continuous JSONL write rejected
    gal = GraphAuditLogger(output_dir=str(tmp_path / "out"), enable_file_logging=False)
    gal.enable_file_logging = True
    gal.output_dir = tmp_path / "out"
    gal.output_dir.mkdir(parents=True, exist_ok=True)
    from ipfs_datasets_py.optimizers.graphrag.audit_logger import (
        AuditEvent,
        EventType,
    )

    with pytest.raises(ObservabilityMutableFileSinkError):
        gal._write_event_to_file(
            AuditEvent.create(EventType.CONFIG_CHANGE, 0, {"x": 1})
        )

    # Logic security attach_file_sink rejected
    with pytest.raises(ObservabilityMutableFileSinkError):
        logic_audit.AuditLogger.attach_file_sink(str(tmp_path / "audit_log.json"))

    # MCP attach rejected
    with pytest.raises(ObservabilityMutableFileSinkError):
        mcp_logger_mod.attach_mcp_file_sink(tmp_path / "mcp_server.log")

    # Alert state authority rejected
    mgr = AlertManager(notifier=_FakeNotifier(), rules=[])
    with pytest.raises(ObservabilityMutableFileSinkError):
        mgr.save_alert_state(tmp_path / "alert_state.json")


def test_explicit_export_still_works(export_only, tmp_path):
    """Explicit deterministic exports remain allowed under a permit."""

    gal = GraphAuditLogger(enable_file_logging=False)
    gal.log_cycle_start(
        data="export",
        context=type(
            "C",
            (),
            {"data_source": "x", "domain": "d", "extraction_strategy": "e"},
        )(),
        max_rounds=1,
        convergence_threshold=0.1,
    )
    out = tmp_path / "audit_trail.json"
    gal.export_json(out)
    assert out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["event_count"] >= 1

    # permit_explicit_observability_export allows guarded path
    with permit_explicit_observability_export():
        assert_mutable_file_sink_allowed(tmp_path / "ok.json", kind="export")

    # Alert export
    mgr = AlertManager(
        notifier=_FakeNotifier(),
        rules=[
            AlertRule(
                rule_id="r-export",
                name="n",
                condition={"==": [1, 1]},
                message_template="m",
            )
        ],
    )
    state_path = tmp_path / "alert_export.json"
    mgr.export_alert_state(state_path)
    assert state_path.is_file()
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload.get("kind") == "alert_state_export"

    # Logging audit export_report
    report_path = tmp_path / "logging_audit.txt"
    export_report("sample report", report_path)
    assert report_path.is_file()


# ---------------------------------------------------------------------------
# Console cannot satisfy progress / completion authority
# ---------------------------------------------------------------------------


def test_console_cannot_satisfy_progress_or_completion(db_primary):
    assert db_primary.console.is_authority is False

    with pytest.raises(ObservabilityConsoleAuthorityError):
        assert_console_not_progress_or_completion_authority(claim_progress=True)

    with pytest.raises(ObservabilityConsoleAuthorityError):
        assert_console_not_progress_or_completion_authority(claim_completion=True)

    with pytest.raises(ObservabilityConsoleAuthorityError):
        assert_console_not_progress_or_completion_authority(console_is_authority=True)

    # Soft check passes
    assert_console_not_progress_or_completion_authority()

    # Snapshot excludes console authority
    snap = db_primary.open_snapshot()
    assert snap.console_is_authority is False
    assert snap.jsonl_scanned is False
    progress = db_primary.catalog.progress()
    assert progress.authority.value == "sequence"
    assert "console" not in progress.authority.value


def test_console_lines_not_in_authority_snapshot(db_primary):
    # Emit console projection lines
    db_primary.console.emit("human readable only", level="info")
    recent = db_primary.console.recent_lines()
    assert recent
    snap = db_primary.open_snapshot()
    # Authority content must not depend on console lines
    body = snap.to_dict() if hasattr(snap, "to_dict") else {}
    assert body.get("console_is_authority", False) is False
    assert "console_lines" not in body
    # Console is_authority remains False even with emitted lines
    assert db_primary.console.is_authority is False


# ---------------------------------------------------------------------------
# Sanitized publication views
# ---------------------------------------------------------------------------


def test_sanitized_publication_excludes_secrets_and_hc_private():
    dirty = {
        "action": "user.login",
        "status": "ok",
        "count": 2,
        "password": "hunter2",
        "token": "eyJhbGciOiJIUzI1NiJ9",
        "api_key": "sk-live-xyz",
        "authorization": "Bearer abc",
        "user_id": "user-42",
        "session_id": "sess-99",
        "client_ip": "192.168.1.10",
        "request_id": "req-abc",
        "raw_payload": {"nested": "secret-blob"},
        "error_stack": "Traceback...",
        "details": {"password": "nested-secret", "metric": 7},
    }
    clean = sanitized_publication_view(dirty)

    # Secrets must not leak as plaintext
    for key in ("password", "token", "api_key", "authorization"):
        assert key not in clean or clean[key] != dirty[key]
        if key in clean:
            assert "hunter2" not in str(clean[key])
            assert "sk-live" not in str(clean[key])

    # High-cardinality private keys stripped
    for key in (
        "user_id",
        "session_id",
        "client_ip",
        "request_id",
        "raw_payload",
        "error_stack",
        "details",
    ):
        assert key not in clean

    # Safe operational fields retained
    assert clean.get("action") == "user.login"
    assert clean.get("status") == "ok"
    assert clean.get("count") == 2


def test_owner_task_pin():
    assert OBSERVABILITY_FILE_SINK_OWNER_TASK == "DQK-079"


def test_validation_script_importable():
    """scripts/validation/validate_duckdb_observability_cutover is loadable."""
    import importlib.util

    path = (
        _REPO_ROOT
        / "scripts"
        / "validation"
        / "validate_duckdb_observability_cutover.py"
    )
    assert path.is_file()
    spec = importlib.util.spec_from_file_location(
        "validate_duckdb_observability_cutover", path
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "run_all")
    assert hasattr(mod, "main")


def test_validation_script_run_all(tmp_path):
    import importlib.util

    path = (
        _REPO_ROOT
        / "scripts"
        / "validation"
        / "validate_duckdb_observability_cutover.py"
    )
    spec = importlib.util.spec_from_file_location(
        "validate_duckdb_observability_cutover_run", path
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    report = mod.run_all(_REPO_ROOT, tmp_path / "val")
    assert report["ok"] is True, report
    assert report["owner_task"] == "DQK-079"
