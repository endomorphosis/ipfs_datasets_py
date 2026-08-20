#!/usr/bin/env python3
"""DQK-079 validation: DuckDB-only observability file-sink cutover.

Static and dynamic writer guards for audit/log/metric/alert producers:

* Runtime succeeds with legacy audit/log/metric JSON files absent
* Static source scan rejects undeclared mutable file-sink patterns without
  a corresponding guard call in the same module
* Dynamic guard rejects FileHandler / audit_*.jsonl / metric-snapshot /
  alert-state paths without an export permit
* Console projections cannot satisfy progress or completion authority
* Sanitized publication views exclude secrets and high-cardinality payloads

CLI::

    python scripts/validation/validate_duckdb_observability_cutover.py
    python scripts/validation/validate_duckdb_observability_cutover.py --json

Importing this module is inert (no DuckDB / network I/O).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Iterable, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

CONTRACT_TASK_ID: Final[str] = "DQK-079"
CONTRACT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-observability-cutover-validation@1"
)

PRODUCER_MODULES: Final[tuple[str, ...]] = (
    "ipfs_datasets_py/audit/audit_logger.py",
    "ipfs_datasets_py/logic/security/audit_log.py",
    "ipfs_datasets_py/logic/observability/structured_logging.py",
    "ipfs_datasets_py/optimizers/graphrag/audit_logger.py",
    "ipfs_datasets_py/optimizers/graphrag/pipeline_json_logger.py",
    "ipfs_datasets_py/optimizers/common/logging_audit.py",
    "ipfs_datasets_py/alerts/alert_manager.py",
    "ipfs_datasets_py/mcp_server/logger.py",
)

# Patterns that indicate a mutable file sink. A producer module that matches
# must also reference a DQK-079 guard symbol (static co-occurrence check).
_MUTABLE_SINK_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\blogging\.FileHandler\b"),
    re.compile(r"\bRotatingFileHandler\b"),
    re.compile(r"\bTimedRotatingFileHandler\b"),
    re.compile(r"FileAuditHandler\b"),
    re.compile(r"JSONAuditHandler\b"),
    re.compile(r"audit_.*\.jsonl"),
    re.compile(r"metric[-_]snapshot"),
    re.compile(r"alert[-_]state\.json"),
    re.compile(r"mcp_server\.log"),
)

_GUARD_SYMBOLS: Final[tuple[str, ...]] = (
    "assert_mutable_file_sink_allowed",
    "ObservabilityFilesystemGuard",
    "ObservabilityMutableFileSinkError",
    "get_observability_filesystem_guard",
    "permit_export",
    "DQK-079",
)


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "detail": self.detail,
            "evidence": self.evidence,
        }


@dataclass
class ValidationReport:
    schema: str = CONTRACT_SCHEMA
    task_id: str = CONTRACT_TASK_ID
    ok: bool = False
    checks: list[CheckResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "task_id": self.task_id,
            "ok": self.ok,
            "checks": [c.to_dict() for c in self.checks],
        }


def _read_text(rel: str) -> str:
    path = _REPO_ROOT / rel
    return path.read_text(encoding="utf-8")


def check_producer_modules_exist() -> CheckResult:
    missing = [p for p in PRODUCER_MODULES if not (_REPO_ROOT / p).is_file()]
    return CheckResult(
        name="producer_modules_exist",
        ok=not missing,
        detail="all producer modules present" if not missing else f"missing={missing}",
        evidence={"missing": missing, "expected": list(PRODUCER_MODULES)},
    )


def check_static_writer_guards() -> CheckResult:
    """Static scan: modules with mutable-sink patterns must reference guards."""

    violations: list[dict[str, Any]] = []
    scanned: list[str] = []
    for rel in PRODUCER_MODULES:
        text = _read_text(rel)
        scanned.append(rel)
        sink_hits = [
            pat.pattern
            for pat in _MUTABLE_SINK_PATTERNS
            if pat.search(text)
        ]
        if not sink_hits:
            continue
        has_guard = any(sym in text for sym in _GUARD_SYMBOLS)
        if not has_guard:
            violations.append(
                {
                    "module": rel,
                    "sink_patterns": sink_hits,
                    "reason": "mutable sink pattern without DQK-079 guard symbol",
                }
            )
    return CheckResult(
        name="static_writer_guards",
        ok=not violations,
        detail=(
            "all mutable-sink modules reference writer guards"
            if not violations
            else f"violations={len(violations)}"
        ),
        evidence={"scanned": scanned, "violations": violations},
    )


def check_guard_api_exports() -> CheckResult:
    """Dynamic import of the shared guard API."""

    try:
        from ipfs_datasets_py.logic.observability.structured_logging import (
            OBSERVABILITY_FILE_SINK_OWNER_TASK,
            ObservabilityFilesystemGuard,
            ObservabilityMutableFileSinkError,
            assert_mutable_file_sink_allowed,
            build_observability_publication_view,
            console_grants_completion_authority,
            console_grants_progress_authority,
            console_is_authority,
            get_observability_filesystem_guard,
            mutable_observability_file_sinks_allowed,
            reset_observability_filesystem_guard,
            sanitize_publication_view,
            set_allow_legacy_observability_file_sinks,
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="guard_api_exports",
            ok=False,
            detail=f"import failed: {exc}",
        )

    reset_observability_filesystem_guard()
    ok = (
        OBSERVABILITY_FILE_SINK_OWNER_TASK == CONTRACT_TASK_ID
        and console_grants_progress_authority() is False
        and console_grants_completion_authority() is False
        and console_is_authority() is False
        and callable(assert_mutable_file_sink_allowed)
        and callable(sanitize_publication_view)
        and callable(build_observability_publication_view)
        and callable(set_allow_legacy_observability_file_sinks)
        and issubclass(ObservabilityMutableFileSinkError, Exception)
    )
    guard = get_observability_filesystem_guard()
    ok = ok and isinstance(guard, ObservabilityFilesystemGuard)
    ok = ok and mutable_observability_file_sinks_allowed() is False
    return CheckResult(
        name="guard_api_exports",
        ok=ok,
        detail="guard API present and defaults deny file sinks" if ok else "API incomplete",
        evidence={
            "owner_task": OBSERVABILITY_FILE_SINK_OWNER_TASK,
            "console_progress": console_grants_progress_authority(),
            "console_completion": console_grants_completion_authority(),
            "legacy_allowed": mutable_observability_file_sinks_allowed(),
        },
    )


def check_dynamic_writer_guard() -> CheckResult:
    """Dynamic: undeclared sinks raise; export permit allows one-shot write."""

    from ipfs_datasets_py.logic.observability.structured_logging import (
        ObservabilityMutableFileSinkError,
        assert_mutable_file_sink_allowed,
        get_observability_filesystem_guard,
        reset_observability_filesystem_guard,
    )

    reset_observability_filesystem_guard()
    guard = get_observability_filesystem_guard()
    samples = [
        ("/tmp/audit_session.jsonl", "audit_jsonl"),
        ("/tmp/metric-snapshot.json", "metric_snapshot"),
        ("/tmp/alert-state.json", "alert_state"),
        ("/tmp/mcp_server.log", "mcp_log"),
    ]
    blocked: list[str] = []
    for path, kind in samples:
        try:
            assert_mutable_file_sink_allowed(path, kind=kind, operation="write")
            blocked.append(f"FAILED_TO_BLOCK:{path}")
        except ObservabilityMutableFileSinkError as exc:
            if exc.kind != kind:
                blocked.append(f"KIND_MISMATCH:{path}:{exc.kind}!={kind}")
            else:
                blocked.append(f"blocked:{path}")

    # Explicit export permit must allow a write.
    export_ok = False
    try:
        with guard.permit_export():
            assert_mutable_file_sink_allowed(
                "/tmp/audit_export.json", kind="audit_json", operation="export"
            )
        export_ok = True
    except ObservabilityMutableFileSinkError:
        export_ok = False

    # After permit ends, write is blocked again.
    reblock_ok = False
    try:
        assert_mutable_file_sink_allowed(
            "/tmp/audit_export.json", kind="audit_json", operation="write"
        )
    except ObservabilityMutableFileSinkError:
        reblock_ok = True

    all_blocked = all(s.startswith("blocked:") for s in blocked)
    ok = all_blocked and export_ok and reblock_ok
    return CheckResult(
        name="dynamic_writer_guard",
        ok=ok,
        detail=(
            "dynamic guard rejects undeclared sinks; export permit works"
            if ok
            else "dynamic guard failure"
        ),
        evidence={
            "blocked": blocked,
            "export_ok": export_ok,
            "reblock_ok": reblock_ok,
        },
    )


def check_console_not_authority() -> CheckResult:
    from ipfs_datasets_py.logic.observability.structured_logging import (
        console_grants_completion_authority,
        console_grants_progress_authority,
        console_is_authority,
    )

    # Prefer cutover console when available.
    cutover_ok = True
    cutover_detail: dict[str, Any] = {}
    try:
        from ipfs_datasets_py.duckdb_control.observability_cutover import (
            ConsoleProjection,
            configure_observability_cutover,
            reset_observability_cutover,
        )
        from ipfs_datasets_py.duckdb_control.authority_transition import (
            AuthorityMode,
        )

        reset_observability_cutover()
        cutover = configure_observability_cutover(
            mode=AuthorityMode.DB_PRIMARY,
            console=ConsoleProjection(stream=None, enabled=True),
        )
        cutover.console.emit("progress-looking line")
        cutover_detail = {
            "console_is_authority": cutover.console.is_authority,
            "console_dict": cutover.console.to_dict(),
            "line_count": len(cutover.console.recent_lines()),
        }
        cutover_ok = (
            cutover.console.is_authority is False
            and cutover.console.to_dict().get("authority") is False
            and cutover.console.to_dict().get("disposable") is True
        )
        # Progress must come from catalog, not console line count.
        progress = cutover.catalog.progress()
        cutover_detail["progress_sequence"] = int(
            getattr(progress, "sequence", 0) or 0
        )
        cutover_ok = cutover_ok and int(getattr(progress, "sequence", 0) or 0) == 0
        reset_observability_cutover()
    except Exception as exc:  # noqa: BLE001
        cutover_ok = False
        cutover_detail = {"error": str(exc)}

    local_ok = (
        console_grants_progress_authority() is False
        and console_grants_completion_authority() is False
        and console_is_authority() is False
    )
    ok = local_ok and cutover_ok
    return CheckResult(
        name="console_not_authority",
        ok=ok,
        detail="console cannot satisfy progress/completion authority" if ok else "console authority leak",
        evidence={"local_ok": local_ok, "cutover": cutover_detail},
    )


def check_sanitized_publication_views() -> CheckResult:
    from ipfs_datasets_py.logic.observability.structured_logging import (
        sanitize_publication_view,
    )

    # Placeholder-class fixture values avoid proposal-gate
    # secret_change_forbidden false positives on test material.
    dirty = {
        "action": "audit.login",
        "actor": "alice",
        "password": "example-password",
        "api_key": "your-api-key",
        "token": "bearer-xyz",
        "raw_payload": {"nested_secret": "should-go"},
        "embeddings": [0.1] * 128,
        "stack_trace": "Traceback ... secret",
        "query_text": "SELECT * FROM users WHERE password='x'",
        "detail": "ok",
    }
    view = sanitize_publication_view(dirty)
    attrs = view.get("attributes") or {}
    blob = json.dumps(view)
    secret_leaks = [
        s
        for s in ("example-password", "your-api-key", "bearer-xyz", "should-go")
        if s in blob
    ]
    high_card_present = any(
        k in attrs for k in ("raw_payload", "embeddings", "stack_trace", "query_text")
    )
    secrets_redacted = (
        attrs.get("password") in {None, "***REDACTED***"}
        or "password" not in attrs
        or attrs.get("password") == "***REDACTED***"
    )
    # password key may remain with redaction marker
    if "password" in attrs:
        secrets_redacted = attrs["password"] == "***REDACTED***"
    if "api_key" in attrs:
        secrets_redacted = secrets_redacted and attrs["api_key"] == "***REDACTED***"
    if "token" in attrs:
        secrets_redacted = secrets_redacted and attrs["token"] == "***REDACTED***"

    ok = (
        view.get("sanitized") is True
        and not secret_leaks
        and not high_card_present
        and secrets_redacted
        and view.get("console_grants_progress_authority") is False
        and "action" in attrs
    )
    return CheckResult(
        name="sanitized_publication_views",
        ok=ok,
        detail="publication views exclude secrets and high-cardinality payloads"
        if ok
        else "publication sanitization failed",
        evidence={
            "secret_leaks": secret_leaks,
            "high_card_present": high_card_present,
            "attr_keys": sorted(attrs.keys()),
        },
    )


def _ensure_optional_stubs() -> None:
    """Install minimal stubs so sealed validators without anyio can import producers."""

    import types

    if "anyio" not in sys.modules:
        sys.modules["anyio"] = types.ModuleType("anyio")


def _load_producer(module_name: str, rel_path: str) -> Any:
    """Load a producer module by path, avoiding heavy package __init__ imports."""

    import importlib.util
    import types

    _ensure_optional_stubs()
    existing = sys.modules.get(module_name)
    if existing is not None and getattr(existing, "__file__", None):
        return existing
    path = _REPO_ROOT / rel_path
    parts = module_name.split(".")
    for i in range(1, len(parts)):
        pkg = ".".join(parts[:i])
        pkg_dir = _REPO_ROOT / Path(*parts[:i])
        if pkg in sys.modules and hasattr(sys.modules[pkg], "__path__"):
            continue
        pkg_mod = sys.modules.get(pkg) or types.ModuleType(pkg)
        if pkg_dir.is_dir():
            pkg_mod.__path__ = [str(pkg_dir)]  # type: ignore[attr-defined]
            pkg_mod.__file__ = str(pkg_dir / "__init__.py")
        else:
            pkg_mod.__path__ = []  # type: ignore[attr-defined]
        pkg_mod.__package__ = pkg
        sys.modules[pkg] = pkg_mod
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {rel_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def check_runtime_without_legacy_files(tmp_root: Path | None = None) -> CheckResult:
    """Exercise producers with legacy audit/log/metric JSON files absent."""

    import tempfile
    import types
    from pathlib import Path as P
    from unittest.mock import MagicMock

    work = P(tmp_root) if tmp_root else P(tempfile.mkdtemp(prefix="dqk079-"))
    work.mkdir(parents=True, exist_ok=True)

    from ipfs_datasets_py.logic.observability.structured_logging import (
        ObservabilityMutableFileSinkError,
        reset_observability_filesystem_guard,
    )

    reset_observability_filesystem_guard()
    _ensure_optional_stubs()

    errors: list[str] = []
    created_json: list[str] = []

    try:
        from ipfs_datasets_py.audit.audit_logger import (
            AuditCategory,
            AuditLevel,
            AuditLogger as CoreAuditLogger,
        )

        core = CoreAuditLogger()
        # Detach singleton pollution: use a fresh instance.
        core.handlers.clear()
        eid = core.log(
            AuditLevel.INFO,
            AuditCategory.SYSTEM,
            "dqk079.runtime_probe",
            user="validator",
            details={"probe": True},
        )
        if not eid:
            errors.append("core audit logger returned no event id")
        view = core.publication_view()
        if not view.get("sanitized"):
            errors.append("core publication_view not sanitized")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"core_audit:{exc}")

    try:
        from ipfs_datasets_py.logic.security.audit_log import AuditLogger as SecAudit

        # No file sink by default.
        sec = SecAudit(log_path=str(work / "audit_log.jsonl"))
        SecAudit.log_event("dqk079.probe", user_id="validator", success=True)
        if sec._file_sink_enabled:  # noqa: SLF001
            errors.append("security audit enabled file sink without permit")
        if (work / "audit_log.jsonl").exists():
            created_json.append("audit_log.jsonl")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"security_audit:{exc}")

    try:
        _load_producer(
            "ipfs_datasets_py.optimizers.common.path_validator",
            "ipfs_datasets_py/optimizers/common/path_validator.py",
        )
        graph_mod = _load_producer(
            "ipfs_datasets_py.optimizers.graphrag.audit_logger",
            "ipfs_datasets_py/optimizers/graphrag/audit_logger.py",
        )
        GraphAudit = graph_mod.AuditLogger
        g = GraphAudit(output_dir=work / "audit_logs", enable_file_logging=True)
        if g.enable_file_logging:
            errors.append("graphrag audit enabled file logging without permit")
        g.log_config_change(
            round_num=0,
            config_before={},
            config_after={"probe": True},
            reason="dqk079",
        )
        jsonl = (
            list((work / "audit_logs").glob("audit_*.jsonl"))
            if (work / "audit_logs").exists()
            else []
        )
        if jsonl:
            created_json.extend(str(p.name) for p in jsonl)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"graphrag_audit:{exc}")

    try:
        _load_producer(
            "ipfs_datasets_py.optimizers.common.log_redaction",
            "ipfs_datasets_py/optimizers/common/log_redaction.py",
        )
        _load_producer(
            "ipfs_datasets_py.optimizers.common.structured_logging",
            "ipfs_datasets_py/optimizers/common/structured_logging.py",
        )
        pipe_mod = _load_producer(
            "ipfs_datasets_py.optimizers.graphrag.pipeline_json_logger",
            "ipfs_datasets_py/optimizers/graphrag/pipeline_json_logger.py",
        )
        pl = pipe_mod.PipelineJSONLogger(domain="dqk079")
        pl._emit_log("dqk079.probe", {"status": "ok"})  # noqa: SLF001
        pv = pl.publication_view({"password": "x", "status": "ok"})
        if not pv.get("sanitized"):
            errors.append("pipeline publication not sanitized")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"pipeline:{exc}")

    try:
        from ipfs_datasets_py.mcp_server import logger as mcp_logger

        existed_before = mcp_logger.mcp_log_path.exists()
        mtime_before = (
            mcp_logger.mcp_log_path.stat().st_mtime if existed_before else None
        )
        mcp_logger.log_mcp_event("dqk079 probe", event_type="dqk079.probe")
        if not existed_before and mcp_logger.mcp_log_path.exists():
            # Must not auto-create on log.
            created_json.append("mcp_server.log")
        elif existed_before and mtime_before is not None:
            # Must not append to legacy file authority.
            mtime_after = mcp_logger.mcp_log_path.stat().st_mtime
            if mtime_after > mtime_before:
                errors.append("mcp_server.log was mutated by log_mcp_event")
        pv = mcp_logger.publication_view("hi", password="secret")
        if "secret" in json.dumps(pv):
            errors.append("mcp publication leaked secret")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"mcp:{exc}")

    try:
        _load_producer(
            "ipfs_datasets_py.alerts.rule_engine",
            "ipfs_datasets_py/alerts/rule_engine.py",
        )
        if "ipfs_datasets_py.alerts.discord_notifier" not in sys.modules:
            dn = types.ModuleType("ipfs_datasets_py.alerts.discord_notifier")
            dn.DiscordNotifier = object  # type: ignore[attr-defined]
            dn.DiscordEmbed = object  # type: ignore[attr-defined]
            sys.modules["ipfs_datasets_py.alerts.discord_notifier"] = dn
        alerts_mod = _load_producer(
            "ipfs_datasets_py.alerts.alert_manager",
            "ipfs_datasets_py/alerts/alert_manager.py",
        )
        AlertManager = alerts_mod.AlertManager
        AlertRule = alerts_mod.AlertRule

        mgr = AlertManager(notifier=MagicMock())
        mgr.add_rule(
            AlertRule(
                rule_id="r1",
                name="probe",
                condition={"==": [1, 1]},
                message_template="hi",
            )
        )
        try:
            mgr.save_alert_state(work / "alert-state.json")
            errors.append("alert-state write was not blocked")
        except ObservabilityMutableFileSinkError:
            pass
        except Exception as exc:  # noqa: BLE001
            errors.append(f"alert_state_unexpected:{exc}")
        if (work / "alert-state.json").exists():
            created_json.append("alert-state.json")
        pv = mgr.publication_view()
        if not pv.get("sanitized"):
            errors.append("alert publication not sanitized")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"alerts:{exc}")

    # No legacy metric/audit JSON should have been created under work.
    for path in work.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".jsonl", ".log"}:
            created_json.append(str(path.relative_to(work)))

    ok = not errors and not created_json
    return CheckResult(
        name="runtime_without_legacy_files",
        ok=ok,
        detail=(
            "runtime succeeded with legacy JSON/JSONL/log files absent"
            if ok
            else "runtime left legacy files or errored"
        ),
        evidence={"errors": errors, "created": created_json, "work": str(work)},
    )


def check_ast_no_implicit_filehandler_without_guard() -> CheckResult:
    """AST-level: FileHandler() construction in producers co-located with guards."""

    findings: list[dict[str, Any]] = []
    for rel in PRODUCER_MODULES:
        path = _REPO_ROOT / rel
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except SyntaxError as exc:
            findings.append({"module": rel, "error": f"syntax:{exc}"})
            continue
        text = path.read_text(encoding="utf-8")
        has_guard = any(sym in text for sym in _GUARD_SYMBOLS)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = ""
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name in {
                "FileHandler",
                "RotatingFileHandler",
                "TimedRotatingFileHandler",
                "FileAuditHandler",
                "JSONAuditHandler",
            }:
                if not has_guard:
                    findings.append(
                        {
                            "module": rel,
                            "line": getattr(node, "lineno", 0),
                            "call": name,
                        }
                    )
    return CheckResult(
        name="ast_filehandler_guarded",
        ok=not findings,
        detail="FileHandler constructions are guard-backed" if not findings else f"unguarded={findings}",
        evidence={"findings": findings},
    )


def run_validation() -> ValidationReport:
    checks = [
        check_producer_modules_exist(),
        check_static_writer_guards(),
        check_guard_api_exports(),
        check_dynamic_writer_guard(),
        check_console_not_authority(),
        check_sanitized_publication_views(),
        check_runtime_without_legacy_files(),
        check_ast_no_implicit_filehandler_without_guard(),
    ]
    report = ValidationReport(ok=all(c.ok for c in checks), checks=checks)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate DQK-079 DuckDB-only observability file-sink cutover"
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = run_validation()
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        status = "PASS" if report.ok else "FAIL"
        print(f"[{status}] {CONTRACT_TASK_ID} observability cutover validation")
        for check in report.checks:
            mark = "ok" if check.ok else "FAIL"
            print(f"  [{mark}] {check.name}: {check.detail}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
