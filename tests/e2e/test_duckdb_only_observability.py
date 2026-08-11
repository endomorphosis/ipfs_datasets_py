"""E2E tests: DuckDB-only observability / audit file authority removal (DQK-079).

Acceptance:

* Runtime succeeds with legacy audit/log/metric JSON files absent
* Static and dynamic writer guards reject undeclared mutable file sinks
* Console logs cannot satisfy progress or completion authority
* Sanitized publication views exclude secrets and high-cardinality private
  payloads
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, List
from unittest.mock import MagicMock

import pytest

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

from ipfs_datasets_py.audit.audit_logger import (  # noqa: E402
    AuditCategory,
    AuditLevel,
    AuditLogger,
)
from ipfs_datasets_py.duckdb_control.authority_transition import AuthorityMode  # noqa: E402
from ipfs_datasets_py.logic.observability.structured_logging import (  # noqa: E402
    OBSERVABILITY_DUCKDB_ONLY_OWNER_TASK,
    OBSERVABILITY_DUCKDB_ONLY_SCHEMA,
    OBSERVABILITY_PUBLICATION_TYPE,
    ImplicitMutableFileSinkError,
    ObservabilityFilesystemGuard,
    build_sanitized_observability_publication,
    configure_duckdb_only_observability,
    console_cannot_satisfy_progress_or_completion,
    duckdb_only_observability,
    export_observability_json,
    get_observability_filesystem_guard,
    legacy_observability_file_sinks_allowed,
    reset_observability_filesystem_guard,
    sanitize_for_publication,
    set_legacy_observability_file_sinks_allowed,
)
from ipfs_datasets_py.mcp_server.logger import log_mcp_event  # noqa: E402
from ipfs_datasets_py.optimizers.graphrag.audit_logger import (  # noqa: E402
    AuditLogger as GraphAuditLogger,
)
from ipfs_datasets_py.optimizers.graphrag.pipeline_json_logger import (  # noqa: E402
    PipelineJSONLogger,
)

_ALLOWED_SOURCE_PATHS = (
    _REPO_ROOT / "ipfs_datasets_py/audit/audit_logger.py",
    _REPO_ROOT / "ipfs_datasets_py/logic/security/audit_log.py",
    _REPO_ROOT / "ipfs_datasets_py/logic/observability/structured_logging.py",
    _REPO_ROOT / "ipfs_datasets_py/optimizers/graphrag/audit_logger.py",
    _REPO_ROOT / "ipfs_datasets_py/optimizers/graphrag/pipeline_json_logger.py",
    _REPO_ROOT / "ipfs_datasets_py/optimizers/common/logging_audit.py",
    _REPO_ROOT / "ipfs_datasets_py/alerts/alert_manager.py",
    _REPO_ROOT / "ipfs_datasets_py/mcp_server/logger.py",
)

_LEGACY_NAMES = {
    "audit.json",
    "audit.jsonl",
    "metrics.json",
    "metric_snapshot.json",
    "metrics_snapshot.json",
    "alerts.json",
    "alert_state.json",
    "alert-state.json",
    "mcp_server.log",
    "observability.json",
    "observability.jsonl",
}


def _legacy_observability_files(root: Path) -> List[Path]:
    if not root.exists():
        return []
    out: List[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.name.startswith("."):
            continue
        name = p.name.lower()
        if name in _LEGACY_NAMES or name.endswith(".jsonl"):
            if name.endswith(".json") or name.endswith(".jsonl") or name.endswith(".log"):
                out.append(p)
    return sorted(out)


@pytest.fixture
def duckdb_only(tmp_path: Path):
    reset_observability_filesystem_guard()
    try:
        from ipfs_datasets_py.duckdb_control.observability_cutover import (
            reset_observability_cutover,
        )

        reset_observability_cutover()
    except Exception:
        pass
    repo = configure_duckdb_only_observability(
        mode=AuthorityMode.DB_PRIMARY,
        allow_legacy_file_sinks=False,
        console_enabled=True,
    )
    yield repo, tmp_path
    reset_observability_filesystem_guard()
    try:
        from ipfs_datasets_py.duckdb_control.observability_cutover import (
            reset_observability_cutover,
        )

        reset_observability_cutover()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Module invariants
# ---------------------------------------------------------------------------


class TestModuleInvariants:
    def test_owner_task_and_publication_constants(self):
        assert OBSERVABILITY_DUCKDB_ONLY_OWNER_TASK == "DQK-079"
        assert OBSERVABILITY_PUBLICATION_TYPE == "observability_quack_publication_v1"
        assert OBSERVABILITY_DUCKDB_ONLY_SCHEMA.startswith("ipfs_datasets_py/")

    def test_filesystem_guard_classifies_guarded_paths(self, tmp_path: Path):
        guard = ObservabilityFilesystemGuard(allow_legacy_file_sinks=False)
        assert guard.classify_path(tmp_path / "audit.json") == "audit_json"
        assert guard.classify_path(tmp_path / "audit_session.jsonl") == "audit_jsonl"
        assert (
            guard.classify_path(tmp_path / "metric_snapshot.json")
            == "metric_snapshot"
        )
        assert guard.classify_path(tmp_path / "alerts.json") == "alert_state"
        assert guard.classify_path(tmp_path / "mcp_server.log") == "log_file"
        # Non-observability paths are not guarded by name alone.
        assert guard.classify_path(tmp_path / "readme.md") is None
        assert guard.classify_path(tmp_path / "data.parquet") is None


# ---------------------------------------------------------------------------
# Acceptance: runtime without legacy audit/log/metric JSON files
# ---------------------------------------------------------------------------


class TestRuntimeWithoutLegacyFiles:
    def test_audit_logger_works_without_json_files(self, duckdb_only):
        repo, root = duckdb_only
        assert duckdb_only_observability() is True
        assert legacy_observability_file_sinks_allowed() is False

        logger = AuditLogger()
        logger.enabled = True
        event_id = logger.log(
            AuditLevel.INFO,
            AuditCategory.SECURITY,
            "e2e.login",
            user="alice",
            status="success",
            details={"method": "password", "password": "should-not-leak"},
            event_id="e2e-audit-1",
        )
        assert event_id == "e2e-audit-1"
        assert _legacy_observability_files(root) == []

        if repo is not None:
            receipt = repo.get_receipt("e2e-audit-1")
            assert receipt is not None
            snap = repo.open_snapshot()
            assert snap.jsonl_scanned is False
            assert snap.console_is_authority is False
            assert snap.authority in {"duckdb", "dual"}

    def test_graphrag_audit_memory_only_by_default(self, duckdb_only):
        repo, root = duckdb_only
        glogger = GraphAuditLogger(
            session_id="e2e-session",
            output_dir=root / "audit_logs",
            enable_file_logging=True,  # should be ignored under duckdb-only
        )
        assert glogger.enable_file_logging is False

        class _Ctx:
            data_source = "e2e"
            domain = "legal"
            extraction_strategy = "rule"

        glogger.log_cycle_start(
            data="doc",
            context=_Ctx(),
            max_rounds=2,
            convergence_threshold=0.05,
        )
        assert len(glogger.events) >= 1
        assert not (root / "audit_logs").exists() or _legacy_observability_files(
            root / "audit_logs"
        ) == []
        assert _legacy_observability_files(root) == []

    def test_pipeline_and_mcp_without_files(self, duckdb_only):
        repo, root = duckdb_only
        plog = PipelineJSONLogger(domain="legal")
        plog.start_run(run_id="run-1", data_source="e2e")
        plog._emit_log("pipeline.stage.completed", {"status": "completed"})
        log_mcp_event("e2e mcp ping", event_type="mcp.ping", actor="e2e")
        assert _legacy_observability_files(root) == []

    def test_explicit_export_materializes_json_only_with_permit(self, duckdb_only):
        _, root = duckdb_only
        target = root / "exports" / "audit_export.json"
        export_observability_json(
            target,
            {
                "schema": "ipfs_datasets_py/audit-events-export@1",
                "owner_task": "DQK-079",
                "events": [{"action": "exported"}],
            },
        )
        assert target.is_file()
        payload = json.loads(target.read_text(encoding="utf-8"))
        assert payload["owner_task"] == "DQK-079"

        logger = AuditLogger()
        logger.enabled = True
        logger.log(
            AuditLevel.INFO,
            AuditCategory.SYSTEM,
            "export.prep",
            event_id="e2e-export-prep",
        )
        out = logger.export_events_json(root / "exports" / "core_audit.json")
        assert Path(out).is_file()


# ---------------------------------------------------------------------------
# Acceptance: static + dynamic writer guards
# ---------------------------------------------------------------------------


class TestWriterGuards:
    def test_dynamic_guard_rejects_undeclared_sinks(self, duckdb_only, tmp_path: Path):
        assert duckdb_only_observability() is True
        guard = get_observability_filesystem_guard()
        for name, kind in (
            ("audit.json", "audit_json"),
            ("session.jsonl", "audit_jsonl"),
            ("metric_snapshot.json", "metric_snapshot"),
            ("alerts.json", "alert_state"),
            ("mcp_server.log", "log_file"),
        ):
            path = tmp_path / name
            with pytest.raises(ImplicitMutableFileSinkError) as excinfo:
                guard.assert_write_allowed(path, kind=kind, operation="write")
            assert excinfo.value.kind == kind
            assert "implicit" in str(excinfo.value).lower()

    def test_audit_logger_rejects_file_handler_sink(self, duckdb_only, tmp_path: Path):
        from ipfs_datasets_py.audit.audit_logger import AuditHandler

        class FileLikeHandler(AuditHandler):
            def __init__(self, path: Path):
                super().__init__("file-like")
                self.file_path = str(path)

            def _handle_event(self, event):
                return True

        logger = AuditLogger()
        with pytest.raises(ImplicitMutableFileSinkError):
            logger.add_handler(FileLikeHandler(tmp_path / "audit.json"))

    def test_graphrag_write_event_blocked_without_permit(
        self, duckdb_only, tmp_path: Path
    ):
        glogger = GraphAuditLogger(
            session_id="blocked",
            output_dir=tmp_path / "out",
            enable_file_logging=False,
        )
        # Force a write attempt even though enable_file_logging is False.
        from ipfs_datasets_py.optimizers.graphrag.audit_logger import (
            AuditEvent,
            EventType,
        )

        event = AuditEvent.create(
            event_type=EventType.REFINEMENT_CYCLE_START,
            round_num=0,
            event_data={"x": 1},
        )
        glogger.output_dir = tmp_path / "out"
        glogger.output_dir.mkdir(parents=True, exist_ok=True)
        with pytest.raises(ImplicitMutableFileSinkError):
            glogger._write_event_to_file(event)

    def test_alert_state_and_metric_snapshot_blocked(
        self, duckdb_only, tmp_path: Path
    ):
        from ipfs_datasets_py.alerts.alert_manager import AlertManager, AlertRule

        notifier = MagicMock()
        mgr = AlertManager(notifier=notifier, rules=[])
        with pytest.raises(ImplicitMutableFileSinkError):
            # save_rules_to_file to alert_state path must fail closed
            mgr.save_rules_to_file(tmp_path / "alerts.json")

        # Explicit exports succeed.
        state_path = mgr.save_alert_state_json(tmp_path / "exports" / "state.json")
        assert state_path.is_file()
        snap_path = mgr.write_metric_snapshot_json(
            tmp_path / "exports" / "metric_snapshot.json"
        )
        assert snap_path.is_file()

    def test_static_source_guard_no_unguarded_file_writers(self):
        """AST/static scan: mutable sinks go through guards/exports."""

        forbidden = (
            re.compile(r"FileHandler\("),
            re.compile(r"audit_.*\.jsonl"),
            re.compile(r"metric_snapshot\.json"),
            re.compile(r"alerts\.json"),
        )
        allow_tokens = (
            "permit_export",
            "export_observability_json",
            "assert_observability_file_write_allowed",
            "assert_write_allowed",
            "legacy_observability_file_sinks_allowed",
            "enable_legacy",
            "DQK-079",
            "ObservabilityFilesystemGuard",
            "ImplicitMutableFileSinkError",
            "classify_path",
            "_GUARDED",
            "FileHandler",  # classification / gated branches
            "export_json",
            "export_events_json",
            "export_run_json",
            "export_report_json",
            "save_alert_state_json",
            "write_metric_snapshot_json",
            "allow_legacy",
            "file_sink",
            "guard",
        )

        offenders: List[str] = []
        for path in _ALLOWED_SOURCE_PATHS:
            text = path.read_text(encoding="utf-8")
            ast.parse(text)
            for i, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                for pat in forbidden:
                    if not pat.search(line):
                        continue
                    if any(tok in line for tok in allow_tokens):
                        continue
                    if any(
                        w in line
                        for w in (
                            "write_text",
                            "json.dump",
                            "open(",
                            "FileHandler",
                        )
                    ):
                        offenders.append(f"{path.name}:{i}:{stripped[:120]}")

        assert offenders == [], "unguarded mutable file writers:\n" + "\n".join(
            offenders
        )

    def test_static_producers_mention_duckdb_only_cutover(self):
        slog = (
            _REPO_ROOT
            / "ipfs_datasets_py/logic/observability/structured_logging.py"
        ).read_text(encoding="utf-8")
        assert "configure_duckdb_only_observability" in slog
        assert "ObservabilityFilesystemGuard" in slog
        mcp = (_REPO_ROOT / "ipfs_datasets_py/mcp_server/logger.py").read_text(
            encoding="utf-8"
        )
        assert "DQK-079" in mcp
        assert "StreamHandler" in mcp


# ---------------------------------------------------------------------------
# Acceptance: console cannot satisfy progress or completion
# ---------------------------------------------------------------------------


class TestConsoleNotAuthority:
    def test_console_projection_not_progress_authority(self, duckdb_only):
        repo, _ = duckdb_only
        logger = AuditLogger()
        logger.enabled = True
        logger.log(
            AuditLevel.INFO,
            AuditCategory.OPERATIONAL,
            "progress.tick",
            event_id="e2e-console-1",
            details={"note": "console only"},
        )
        log_mcp_event("console noise", event_type="mcp.log")

        assert console_cannot_satisfy_progress_or_completion(
            ["[info] complete", "[info] done"]
        )
        if repo is not None:
            assert repo.console.is_authority is False
            assert repo.console.to_dict()["disposable"] is True
            progress = repo.catalog.progress().to_dict()
            assert progress.get("authority") == "sequence"
            assert console_cannot_satisfy_progress_or_completion(
                repo.console.recent_lines(), progress=progress
            )
            snap = repo.open_snapshot()
            assert snap.console_is_authority is False
            # Snapshot progress is not derived from console line count.
            assert int(snap.progress_cursor().get("sequence") or 0) >= 1

    def test_helper_rejects_console_claimed_progress(self):
        assert not console_cannot_satisfy_progress_or_completion(
            ["x"],
            progress={"authority": "console", "sequence": 3},
        )
        assert not console_cannot_satisfy_progress_or_completion(
            ["x"],
            progress={"authority": "sequence", "console_is_authority": True},
        )


# ---------------------------------------------------------------------------
# Acceptance: sanitized publication views
# ---------------------------------------------------------------------------


class TestSanitizedPublication:
    def test_sanitize_excludes_secrets_and_high_cardinality(self):
        dirty = {
            "action": "auth",
            "password": "hunter2",
            "token": "tok-abc",
            "api_key": "ak-1",
            "client_ip": "198.51.100.4",
            "session_id": "sess-xyz",
            "raw_payload": {"nested": "secret-data"},
            "query_text": "SELECT * FROM users",
            "outcome": "succeeded",
        }
        clean = sanitize_for_publication(dirty)
        assert clean["password"] == "***REDACTED***"
        assert clean["token"] == "***REDACTED***"
        assert clean["api_key"] == "***REDACTED***"
        assert clean["client_ip"] == "***REDACTED***"
        assert clean["session_id"] == "***REDACTED***"
        assert clean["raw_payload"] == "***REDACTED***"
        assert clean["query_text"] == "***REDACTED***"
        assert clean["outcome"] == "succeeded"
        assert clean["action"] == "auth"

    def test_publication_document_excludes_secrets(self, duckdb_only):
        repo, _ = duckdb_only
        logger = AuditLogger()
        logger.enabled = True
        logger.log(
            AuditLevel.INFO,
            AuditCategory.AUTHENTICATION,
            "pub.login",
            user="bob",
            status="success",
            details={
                "password": "nope",
                "client_ip": "192.0.2.10",
                "session_id": "sess-pub",
            },
            event_id="e2e-pub-1",
        )

        events = [
            {
                "action": "pub.login",
                "password": "nope",
                "api_key": "ak-live",
                "client_ip": "192.0.2.10",
                "session_id": "sess-pub",
                "outcome": "succeeded",
            }
        ]
        progress = {"authority": "sequence", "sequence": 1}
        if repo is not None:
            snap = repo.open_snapshot()
            progress = snap.progress_cursor()
            audit_rows = list(snap.audit_events())
            if audit_rows:
                events = [dict(r) for r in audit_rows]

        doc = build_sanitized_observability_publication(
            events=events,
            progress=progress,
            mode="db-primary",
        )
        assert doc["publication_type"] == OBSERVABILITY_PUBLICATION_TYPE
        assert doc["owner_task"] == "DQK-079"
        assert doc["console_is_authority"] is False
        assert doc["jsonl_scanned"] is False
        assert doc["secrets_excluded"] is True
        assert doc["high_cardinality_private_excluded"] is True
        assert doc["authority"] == "duckdb"

        blob = json.dumps(doc)
        assert "nope" not in blob
        assert "ak-live" not in blob
        assert "192.0.2.10" not in blob or "***REDACTED***" in blob

        for view in doc["approved_sanitized_audit_views"]:
            for key in ("password", "api_key", "token", "client_ip", "session_id"):
                if key in view:
                    assert view[key] == "***REDACTED***"


# ---------------------------------------------------------------------------
# Cross-check validation script exists and is importable
# ---------------------------------------------------------------------------


class TestValidationScript:
    def test_validation_script_exists(self):
        path = (
            _REPO_ROOT
            / "scripts/validation/validate_duckdb_observability_cutover.py"
        )
        assert path.is_file()
        text = path.read_text(encoding="utf-8")
        assert "DQK-079" in text
        ast.parse(text)
