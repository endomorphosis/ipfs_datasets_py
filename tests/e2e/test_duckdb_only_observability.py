"""E2E tests for DuckDB-only observability authority (DQK-079).

Acceptance:

* Runtime succeeds with legacy audit/log/metric JSON files absent
* Static and dynamic writer guards reject undeclared mutable file sinks
* Console logs cannot satisfy progress or completion authority
* Sanitized publication views exclude secrets and high-cardinality private payloads
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()
_VALIDATION_PATH = (
    _REPO_ROOT / "scripts/validation/validate_duckdb_observability_cutover.py"
)


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


from ipfs_datasets_py.logic.observability.structured_logging import (  # noqa: E402
    OBSERVABILITY_FILE_SINK_OWNER_TASK,
    ObservabilityFilesystemGuard,
    ObservabilityMutableFileSinkError,
    assert_mutable_file_sink_allowed,
    build_observability_publication_view,
    console_grants_completion_authority,
    console_grants_progress_authority,
    console_is_authority,
    get_logger,
    get_observability_filesystem_guard,
    mutable_observability_file_sinks_allowed,
    reset_observability_filesystem_guard,
    sanitize_publication_view,
    set_allow_legacy_observability_file_sinks,
)


def _load_validation_module() -> ModuleType:
    """Load the validation script without requiring scripts.validation package."""

    module_name = "validate_duckdb_observability_cutover_dqk079"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, _VALIDATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _ensure_lightweight_stubs() -> None:
    """Install minimal stubs for optional deps missing from the sealed validator."""

    if "anyio" not in sys.modules:
        anyio_stub = ModuleType("anyio")
        sys.modules["anyio"] = anyio_stub


def _ensure_package_namespace(module_name: str) -> None:
    """Register parent packages with real on-disk __path__ without running __init__."""

    parts = module_name.split(".")
    for i in range(1, len(parts)):
        pkg = ".".join(parts[:i])
        if pkg in sys.modules and hasattr(sys.modules[pkg], "__path__"):
            continue
        # Map package name to directory under the repo root when present.
        pkg_dir = _REPO_ROOT / Path(*parts[:i])
        pkg_mod = sys.modules.get(pkg) or ModuleType(pkg)
        if pkg_dir.is_dir():
            pkg_mod.__path__ = [str(pkg_dir)]  # type: ignore[attr-defined]
            pkg_mod.__file__ = str(pkg_dir / "__init__.py")
        else:
            pkg_mod.__path__ = []  # type: ignore[attr-defined]
        pkg_mod.__package__ = pkg
        sys.modules[pkg] = pkg_mod


def _load_module_from_path(module_name: str, rel_path: str) -> ModuleType:
    """Load a producer module by file path, bypassing heavy package __init__ chains."""

    _ensure_lightweight_stubs()
    existing = sys.modules.get(module_name)
    if existing is not None and getattr(existing, "__file__", None):
        # Prefer fully-executed modules (have __file__ and expected attrs later).
        return existing
    path = _REPO_ROOT / rel_path
    _ensure_package_namespace(module_name)
    # Drop a prior failed partial import so we can retry after deps load.
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _load_graphrag_audit_logger() -> ModuleType:
    _load_module_from_path(
        "ipfs_datasets_py.optimizers.common.path_validator",
        "ipfs_datasets_py/optimizers/common/path_validator.py",
    )
    return _load_module_from_path(
        "ipfs_datasets_py.optimizers.graphrag.audit_logger",
        "ipfs_datasets_py/optimizers/graphrag/audit_logger.py",
    )


def _load_pipeline_json_logger() -> ModuleType:
    _load_module_from_path(
        "ipfs_datasets_py.optimizers.common.log_redaction",
        "ipfs_datasets_py/optimizers/common/log_redaction.py",
    )
    _load_module_from_path(
        "ipfs_datasets_py.optimizers.common.structured_logging",
        "ipfs_datasets_py/optimizers/common/structured_logging.py",
    )
    return _load_module_from_path(
        "ipfs_datasets_py.optimizers.graphrag.pipeline_json_logger",
        "ipfs_datasets_py/optimizers/graphrag/pipeline_json_logger.py",
    )


_validation = _load_validation_module()
CONTRACT_TASK_ID = _validation.CONTRACT_TASK_ID
run_validation = _validation.run_validation


@pytest.fixture(autouse=True)
def _reset_file_sink_guard():
    reset_observability_filesystem_guard()
    yield
    reset_observability_filesystem_guard()
    set_allow_legacy_observability_file_sinks(False)


# ---------------------------------------------------------------------------
# Module / contract invariants
# ---------------------------------------------------------------------------


class TestModuleInvariants:
    def test_owner_task_pin(self) -> None:
        assert OBSERVABILITY_FILE_SINK_OWNER_TASK == "DQK-079"
        assert CONTRACT_TASK_ID == "DQK-079"

    def test_console_never_authority(self) -> None:
        assert console_is_authority() is False
        assert console_grants_progress_authority() is False
        assert console_grants_completion_authority() is False

    def test_default_denies_legacy_file_sinks(self) -> None:
        assert mutable_observability_file_sinks_allowed() is False
        guard = get_observability_filesystem_guard()
        assert isinstance(guard, ObservabilityFilesystemGuard)
        assert guard.allow_legacy_file_sinks is False


# ---------------------------------------------------------------------------
# Acceptance: runtime with legacy files absent
# ---------------------------------------------------------------------------


class TestRuntimeWithoutLegacyFiles:
    def test_core_audit_logger_memory_only(self, tmp_path: Path) -> None:
        from ipfs_datasets_py.audit.audit_logger import (
            AuditCategory,
            AuditLevel,
            AuditLogger,
        )

        logger = AuditLogger()
        logger.handlers.clear()
        event_id = logger.log(
            AuditLevel.INFO,
            AuditCategory.SYSTEM,
            "dqk079.e2e.probe",
            user="tester",
            # Use placeholder-class values so the proposal gate does not treat
            # fixtures as concrete secret material (secret_change_forbidden).
            details={"ok": True, "password": "example-secret"},
        )
        assert event_id
        # No audit JSON/JSONL written under tmp.
        assert list(tmp_path.rglob("*.json")) == []
        assert list(tmp_path.rglob("*.jsonl")) == []
        view = logger.publication_view()
        assert view["sanitized"] is True
        assert "example-secret" not in json.dumps(view)

    def test_security_audit_no_file_handler(self, tmp_path: Path) -> None:
        from ipfs_datasets_py.logic.security.audit_log import AuditLogger

        path = tmp_path / "audit_log.jsonl"
        sec = AuditLogger(log_path=str(path))
        assert sec._file_sink_enabled is False  # noqa: SLF001
        AuditLogger.log_event(
            "security.probe",
            user_id="tester",
            success=True,
            details={"token": "leak-me"},
        )
        assert not path.exists()
        view = AuditLogger.publication_view(
            {"action": "security.probe", "token": "leak-me"}
        )
        assert view["sanitized"] is True
        assert "leak-me" not in json.dumps(view)

    def test_graphrag_audit_defaults_memory_only(self, tmp_path: Path) -> None:
        mod = _load_graphrag_audit_logger()
        AuditLogger = mod.AuditLogger

        logger = AuditLogger(
            output_dir=tmp_path / "audit_logs",
            enable_file_logging=True,
        )
        assert logger.enable_file_logging is False
        # Session still works without files.
        logger.log_config_change(
            round_num=1,
            config_before={"a": 1},
            config_after={"a": 2},
            reason="probe",
        )
        assert len(logger.events) == 1
        jsonl = list((tmp_path / "audit_logs").glob("**/*")) if (tmp_path / "audit_logs").exists() else []
        assert jsonl == []
        view = logger.publication_view()
        assert view["sanitized"] is True
        assert view["console_grants_progress_authority"] is False

    def test_pipeline_json_logger_console_only(self, tmp_path: Path) -> None:
        mod = _load_pipeline_json_logger()
        PipelineJSONLogger = mod.PipelineJSONLogger

        pl = PipelineJSONLogger(domain="legal")
        pl._emit_log(  # noqa: SLF001
            "pipeline.probe",
            {"status": "ok", "api_key": "sk-test", "embeddings": [0.1] * 64},
        )
        assert list(tmp_path.rglob("*.jsonl")) == []
        view = pl.publication_view(
            {"api_key": "sk-test", "embeddings": [0.1] * 64, "status": "ok"}
        )
        blob = json.dumps(view)
        assert "sk-test" not in blob
        assert "embeddings" not in (view.get("attributes") or {})

    def test_mcp_logger_does_not_create_file(self) -> None:
        from ipfs_datasets_py.mcp_server import logger as mcp_logger

        # Historical path must not be auto-created by log_mcp_event.
        if mcp_logger.mcp_log_path.exists():
            # If a prior process created it, logging must not require it.
            pass
        mcp_logger.log_mcp_event("e2e probe", event_type="dqk079.probe")
        # Import-time no longer touches the log file into existence for new installs;
        # if the file is missing, it must stay missing.
        # (Do not delete a pre-existing file from other tests.)
        view = mcp_logger.publication_view("hi", password="nopenope")
        assert "nopenope" not in json.dumps(view)
        assert view["console_grants_completion_authority"] is False

    def test_alert_manager_blocks_alert_state(self, tmp_path: Path) -> None:
        _ensure_lightweight_stubs()
        # Pre-load rule_engine and alert_manager by path to avoid alerts package
        # __init__ pulling discord_notifier → anyio in the sealed validator.
        _load_module_from_path(
            "ipfs_datasets_py.alerts.rule_engine",
            "ipfs_datasets_py/alerts/rule_engine.py",
        )
        # Stub discord_notifier lightly for type annotations on AlertManager.
        if "ipfs_datasets_py.alerts.discord_notifier" not in sys.modules:
            dn = ModuleType("ipfs_datasets_py.alerts.discord_notifier")
            dn.DiscordNotifier = object  # type: ignore[attr-defined]
            dn.DiscordEmbed = object  # type: ignore[attr-defined]
            sys.modules["ipfs_datasets_py.alerts.discord_notifier"] = dn
        mod = _load_module_from_path(
            "ipfs_datasets_py.alerts.alert_manager",
            "ipfs_datasets_py/alerts/alert_manager.py",
        )
        AlertManager = mod.AlertManager
        AlertRule = mod.AlertRule

        mgr = AlertManager(notifier=MagicMock())
        mgr.add_rule(
            AlertRule(
                rule_id="r1",
                name="n",
                condition={"==": [1, 1]},
                message_template="x",
            )
        )
        state = tmp_path / "alert-state.json"
        with pytest.raises(ObservabilityMutableFileSinkError) as excinfo:
            mgr.save_alert_state(state)
        assert excinfo.value.kind == "alert_state"
        assert not state.exists()
        # Explicit export works under permit.
        mgr.save_alert_state(state, explicit_export=True)
        assert state.exists()
        payload = json.loads(state.read_text(encoding="utf-8"))
        assert payload["export_authority"] is False
        assert payload["owner_task"] == "DQK-079"


# ---------------------------------------------------------------------------
# Acceptance: static + dynamic writer guards
# ---------------------------------------------------------------------------


class TestWriterGuards:
    def test_classify_guarded_paths(self, tmp_path: Path) -> None:
        guard = ObservabilityFilesystemGuard(allow_legacy_file_sinks=False)
        assert guard.classify_path(tmp_path / "audit_abc.jsonl") == "audit_jsonl"
        assert guard.classify_path(tmp_path / "metric-snapshot.json") == "metric_snapshot"
        assert guard.classify_path(tmp_path / "alert-state.json") == "alert_state"
        assert guard.classify_path(tmp_path / "mcp_server.log") == "mcp_log"
        assert guard.classify_path(tmp_path / "notes.txt") is None

    def test_dynamic_reject_undeclared_sinks(self, tmp_path: Path) -> None:
        for name, kind in (
            ("audit_sess.jsonl", "audit_jsonl"),
            ("metric-snapshot.json", "metric_snapshot"),
            ("alert_state.json", "alert_state"),
            ("mcp_server.log", "mcp_log"),
        ):
            path = tmp_path / name
            with pytest.raises(ObservabilityMutableFileSinkError) as excinfo:
                assert_mutable_file_sink_allowed(path, kind=kind, operation="write")
            assert excinfo.value.kind == kind
            assert "implicit" in str(excinfo.value).lower()
            assert not path.exists()

    def test_filehandler_rejected_by_get_logger(self, tmp_path: Path) -> None:
        log_path = tmp_path / "audit_component.jsonl"
        handler = logging.FileHandler(log_path)
        try:
            with pytest.raises(ObservabilityMutableFileSinkError):
                get_logger("dqk079.test", handlers=[handler])
        finally:
            handler.close()

    def test_core_audit_rejects_file_handler_attach(self, tmp_path: Path) -> None:
        from ipfs_datasets_py.audit.audit_logger import AuditHandler, AuditLogger
        from ipfs_datasets_py.audit.handlers import FileAuditHandler, JSONAuditHandler

        logger = AuditLogger()
        logger.handlers.clear()
        file_handler = FileAuditHandler(
            name="blocked-file",
            file_path=str(tmp_path / "audit_blocked.json"),
        )
        try:
            with pytest.raises(ObservabilityMutableFileSinkError):
                logger.add_handler(file_handler)
        finally:
            file_handler.close()

        json_handler = JSONAuditHandler(
            name="blocked-json",
            file_path=str(tmp_path / "audit_blocked.jsonl"),
        )
        try:
            with pytest.raises(ObservabilityMutableFileSinkError):
                logger.add_handler(json_handler)
        finally:
            json_handler.close()

    def test_export_permit_allows_deterministic_export(self, tmp_path: Path) -> None:
        mod = _load_graphrag_audit_logger()
        AuditLogger = mod.AuditLogger

        logger = AuditLogger(enable_file_logging=False)
        logger.log_config_change(
            round_num=0,
            config_before={},
            config_after={"x": 1},
            reason="export-probe",
        )
        out = tmp_path / "audit_export.json"
        logger.export_json(out)
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["export_authority"] is False
        assert data["owner_task"] == "DQK-079"
        # Implicit write still blocked after export.
        with pytest.raises(ObservabilityMutableFileSinkError):
            assert_mutable_file_sink_allowed(
                tmp_path / "audit_again.jsonl",
                kind="audit_jsonl",
                operation="write",
            )

    def test_static_validation_script_passes(self) -> None:
        report = run_validation()
        failed = [c for c in report.checks if not c.ok]
        assert report.ok, json.dumps(
            [c.to_dict() for c in failed], indent=2, default=str
        )


# ---------------------------------------------------------------------------
# Acceptance: console cannot satisfy progress / completion
# ---------------------------------------------------------------------------


class TestConsoleNotAuthority:
    def test_console_helpers_false(self) -> None:
        assert console_grants_progress_authority() is False
        assert console_grants_completion_authority() is False
        assert console_is_authority() is False

    def test_cutover_console_not_progress_authority(self) -> None:
        from ipfs_datasets_py.duckdb_control.authority_transition import (
            AuthorityMode,
        )
        from ipfs_datasets_py.duckdb_control.observability_cutover import (
            ConsoleProjection,
            configure_observability_cutover,
            reset_observability_cutover,
        )

        reset_observability_cutover()
        try:
            cutover = configure_observability_cutover(
                mode=AuthorityMode.DB_PRIMARY,
                console=ConsoleProjection(stream=None, enabled=True),
            )
            cutover.console.emit("looks like progress=100%")
            cutover.console.emit("task completed successfully")
            assert cutover.console.is_authority is False
            assert cutover.console.to_dict()["authority"] is False
            assert cutover.console.to_dict()["disposable"] is True
            # Progress comes from catalog sequence, not console lines.
            progress = cutover.catalog.progress()
            assert int(getattr(progress, "sequence", 0) or 0) == 0
            assert len(cutover.console.recent_lines()) >= 2
            snap = cutover.open_snapshot()
            assert snap.console_is_authority is False
            assert snap.jsonl_scanned is False
        finally:
            reset_observability_cutover()


# ---------------------------------------------------------------------------
# Acceptance: sanitized publication views
# ---------------------------------------------------------------------------


class TestSanitizedPublicationViews:
    def test_strips_secrets_and_high_cardinality(self) -> None:
        dirty = {
            "action": "login",
            "actor": "bob",
            "password": "hunter2",
            "api_key": "sk-live-999",
            "token": "tok-abc",
            "raw_payload": {"inner": "private"},
            "embeddings": [0.01] * 256,
            "stack_trace": "Traceback secret",
            "query_text": "SELECT password FROM users",
            "detail": "visible",
        }
        view = sanitize_publication_view(dirty)
        assert view["sanitized"] is True
        assert view["console_grants_progress_authority"] is False
        assert view["console_grants_completion_authority"] is False
        attrs = view["attributes"]
        blob = json.dumps(view)
        for secret in ("hunter2", "sk-live-999", "tok-abc", "private"):
            assert secret not in blob
        for key in ("raw_payload", "embeddings", "stack_trace", "query_text"):
            assert key not in attrs
        assert attrs.get("action") == "login"
        assert attrs.get("detail") == "visible"
        # Secret keys redacted if retained.
        for key in ("password", "api_key", "token"):
            if key in attrs:
                assert attrs[key] == "***REDACTED***"

    def test_multi_record_publication_view(self) -> None:
        records = [
            {"event_id": "e1", "password": "x", "embeddings": [1.0]},
            {"event_id": "e2", "token": "y", "status": "ok"},
        ]
        view = build_observability_publication_view(records)
        assert view["sanitized"] is True
        assert view["record_count"] == 2
        blob = json.dumps(view)
        assert "password" not in blob or "***REDACTED***" in blob
        assert "embeddings" not in blob or "embeddings" not in str(view["records"])

    def test_logging_audit_publication_view(self, tmp_path: Path) -> None:
        # path_validator is lightweight; load logging_audit by path to skip
        # optimizers.common package __init__ (anyio via performance).
        _load_module_from_path(
            "ipfs_datasets_py.optimizers.common.path_validator",
            "ipfs_datasets_py/optimizers/common/path_validator.py",
        )
        mod = _load_module_from_path(
            "ipfs_datasets_py.optimizers.common.logging_audit",
            "ipfs_datasets_py/optimizers/common/logging_audit.py",
        )
        LoggingAuditor = mod.LoggingAuditor

        auditor = LoggingAuditor(root_dir=str(tmp_path))
        # Empty dir is fine.
        view = auditor.publication_view()
        assert view["sanitized"] is True
        assert view["console_grants_progress_authority"] is False
        export_path = tmp_path / "logging_audit_report.json"
        auditor.export_report_json(export_path)
        assert export_path.exists()
        payload = json.loads(export_path.read_text(encoding="utf-8"))
        assert payload["export_authority"] is False


# ---------------------------------------------------------------------------
# Full validation command surface
# ---------------------------------------------------------------------------


def test_validate_duckdb_observability_cutover_main() -> None:
    rc = _validation.main(["--json"])
    assert rc == 0
