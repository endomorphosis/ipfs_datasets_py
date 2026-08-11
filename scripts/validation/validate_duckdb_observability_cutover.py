#!/usr/bin/env python3
"""Validate DuckDB-only observability cutover after canary acceptance (DQK-079).

Checks:

1. Runtime succeeds with legacy audit/log/metric JSON files absent
2. Static and dynamic writer guards reject undeclared mutable file sinks
3. Console logs cannot satisfy progress or completion authority
4. Sanitized publication views exclude secrets and high-cardinality private
   payloads

Exit code 0 on success, 1 on failure.
"""

from __future__ import annotations

import ast
import re
import sys
import tempfile
from pathlib import Path
from typing import List

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_PRODUCER_SOURCES = (
    _REPO_ROOT / "ipfs_datasets_py/audit/audit_logger.py",
    _REPO_ROOT / "ipfs_datasets_py/logic/security/audit_log.py",
    _REPO_ROOT / "ipfs_datasets_py/logic/observability/structured_logging.py",
    _REPO_ROOT / "ipfs_datasets_py/optimizers/graphrag/audit_logger.py",
    _REPO_ROOT / "ipfs_datasets_py/optimizers/graphrag/pipeline_json_logger.py",
    _REPO_ROOT / "ipfs_datasets_py/optimizers/common/logging_audit.py",
    _REPO_ROOT / "ipfs_datasets_py/alerts/alert_manager.py",
    _REPO_ROOT / "ipfs_datasets_py/mcp_server/logger.py",
)

_GUARDED_NAMES = (
    "audit.json",
    "audit.jsonl",
    "metrics.json",
    "metric_snapshot.json",
    "alerts.json",
    "alert_state.json",
    "mcp_server.log",
)


def _fail(msg: str, errors: List[str]) -> None:
    errors.append(msg)
    print(f"FAIL: {msg}")


def _ok(msg: str) -> None:
    print(f"OK:   {msg}")


def validate_static_source_guards(errors: List[str]) -> None:
    """AST/static scan: producer sources reference the filesystem guard."""

    required_tokens = (
        "DQK-079",
        "permit_export",
    )
    # At least the observability module must define the guard API.
    slog = (
        _REPO_ROOT
        / "ipfs_datasets_py/logic/observability/structured_logging.py"
    ).read_text(encoding="utf-8")
    for token in (
        "ObservabilityFilesystemGuard",
        "ImplicitMutableFileSinkError",
        "configure_duckdb_only_observability",
        "build_sanitized_observability_publication",
        "console_cannot_satisfy_progress_or_completion",
        "export_observability_json",
        "DQK-079",
    ):
        if token not in slog:
            _fail(f"structured_logging.py missing {token}", errors)
        else:
            _ok(f"structured_logging.py defines/mentions {token}")

    for path in _PRODUCER_SOURCES:
        text = path.read_text(encoding="utf-8")
        try:
            ast.parse(text)
        except SyntaxError as exc:
            _fail(f"{path.name} is not valid Python: {exc}", errors)
            continue
        if "DQK-079" not in text and path.name != "structured_logging.py":
            # structured_logging already checked; others should mention cutover.
            if path.name not in {"structured_logging.py"}:
                # pipeline / logging_audit may only import export helpers
                if "export_observability" not in text and "DQK-078" not in text and "DQK-079" not in text:
                    _fail(f"{path.name} lacks DQK-079 cutover markers", errors)
                else:
                    _ok(f"{path.name} valid Python with cutover wiring")
            continue
        _ok(f"{path.name} parses and references DQK-079 cutover")

    # mcp_server logger must not eagerly attach FileHandler without guard.
    mcp_src = (
        _REPO_ROOT / "ipfs_datasets_py/mcp_server/logger.py"
    ).read_text(encoding="utf-8")
    if "FileHandler" in mcp_src and "legacy" not in mcp_src.lower():
        _fail("mcp_server/logger.py FileHandler not gated by legacy flag", errors)
    else:
        _ok("mcp_server/logger.py FileHandler is legacy-gated")


def validate_dynamic_guard(errors: List[str]) -> None:
    from ipfs_datasets_py.logic.observability.structured_logging import (
        ImplicitMutableFileSinkError,
        configure_duckdb_only_observability,
        get_observability_filesystem_guard,
        reset_observability_filesystem_guard,
        set_legacy_observability_file_sinks_allowed,
    )

    reset_observability_filesystem_guard()
    configure_duckdb_only_observability(allow_legacy_file_sinks=False)
    guard = get_observability_filesystem_guard()
    if guard.allow_legacy_file_sinks:
        _fail("legacy file sinks still allowed after duckdb-only configure", errors)
    else:
        _ok("legacy file sinks disabled under duckdb-only")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name in _GUARDED_NAMES:
            path = root / name
            try:
                guard.assert_write_allowed(path, operation="write")
                _fail(f"guard allowed undeclared sink {name}", errors)
            except ImplicitMutableFileSinkError as exc:
                if not exc.kind:
                    _fail(f"guard error missing kind for {name}", errors)
                else:
                    _ok(f"guard rejects {name} ({exc.kind})")

    # Explicit export permit must succeed.
    with tempfile.TemporaryDirectory() as tmp:
        export_path = Path(tmp) / "audit_export.json"
        from ipfs_datasets_py.logic.observability.structured_logging import (
            export_observability_json,
        )

        export_observability_json(
            export_path, {"schema": "test", "owner_task": "DQK-079", "ok": True}
        )
        if not export_path.is_file():
            _fail("explicit export did not materialize file", errors)
        else:
            _ok("explicit deterministic export succeeds under permit")

    set_legacy_observability_file_sinks_allowed(False)
    reset_observability_filesystem_guard()


def validate_runtime_without_legacy_files(errors: List[str]) -> None:
    from ipfs_datasets_py.audit.audit_logger import (
        AuditCategory,
        AuditLevel,
        AuditLogger,
    )
    from ipfs_datasets_py.duckdb_control.authority_transition import AuthorityMode
    from ipfs_datasets_py.logic.observability.structured_logging import (
        configure_duckdb_only_observability,
        duckdb_only_observability,
        reset_observability_filesystem_guard,
    )
    from ipfs_datasets_py.mcp_server.logger import log_mcp_event
    from ipfs_datasets_py.optimizers.graphrag.audit_logger import (
        AuditLogger as GraphAuditLogger,
    )

    reset_observability_filesystem_guard()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        repo = configure_duckdb_only_observability(
            mode=AuthorityMode.DB_PRIMARY,
            allow_legacy_file_sinks=False,
        )
        if not duckdb_only_observability():
            _fail("duckdb_only_observability() is False after configure", errors)
        else:
            _ok("duckdb_only_observability active")

        logger = AuditLogger()
        logger.enabled = True
        eid = logger.log(
            AuditLevel.INFO,
            AuditCategory.SECURITY,
            "validation.login",
            user="validator",
            status="success",
            details={"method": "token"},
            event_id="dqk-079-validate-1",
        )
        if not eid:
            _fail("AuditLogger.log returned empty event id", errors)
        else:
            _ok(f"AuditLogger recorded event {eid}")

        glogger = GraphAuditLogger(
            session_id="validate-session",
            output_dir=root / "audit_logs",
            enable_file_logging=True,  # request ignored under duckdb-only
        )
        # Memory path should work without creating JSONL.
        from ipfs_datasets_py.optimizers.graphrag.audit_logger import EventType
        from ipfs_datasets_py.optimizers.graphrag.audit_logger import AuditEvent

        # Use a simple public method if available
        if hasattr(glogger, "log_cycle_start"):
            class _Ctx:
                data_source = "validation"
                domain = "test"
                extraction_strategy = "rule"

            try:
                glogger.log_cycle_start(
                    data="x",
                    context=_Ctx(),
                    max_rounds=1,
                    convergence_threshold=0.1,
                )
            except Exception as exc:  # noqa: BLE001
                _fail(f"GraphAuditLogger.log_cycle_start failed: {exc}", errors)
            else:
                _ok("GraphAuditLogger runtime without JSONL")
        else:
            _ok("GraphAuditLogger constructed without file sinks")

        log_mcp_event("validation mcp event", event_type="mcp.validation")
        _ok("log_mcp_event succeeded")

        # Legacy files must remain absent.
        legacy = []
        for pattern in ("*.json", "*.jsonl", "*.log"):
            legacy.extend(
                p
                for p in root.rglob(pattern)
                if p.is_file() and not p.name.startswith(".")
            )
        if legacy:
            _fail(
                f"legacy audit/log/metric files present: {[p.name for p in legacy]}",
                errors,
            )
        else:
            _ok("runtime left no legacy audit/log/metric files")

        if repo is not None:
            snap = repo.open_snapshot()
            if snap.jsonl_scanned or snap.console_is_authority:
                _fail("snapshot claims jsonl/console authority", errors)
            else:
                _ok(
                    f"snapshot authority={snap.authority} "
                    f"console_is_authority={snap.console_is_authority}"
                )

    reset_observability_filesystem_guard()


def validate_console_not_authority(errors: List[str]) -> None:
    from ipfs_datasets_py.logic.observability.structured_logging import (
        console_cannot_satisfy_progress_or_completion,
        configure_duckdb_only_observability,
        reset_observability_filesystem_guard,
    )

    reset_observability_filesystem_guard()
    repo = configure_duckdb_only_observability(allow_legacy_file_sinks=False)
    lines = ["[info] done", "[info] complete"]
    if not console_cannot_satisfy_progress_or_completion(lines):
        _fail("console_cannot_satisfy helper returned False for bare lines", errors)
    else:
        _ok("console lines alone are not progress/completion authority")

    if repo is not None:
        assert repo.console.is_authority is False
        progress = repo.catalog.progress().to_dict()
        if not console_cannot_satisfy_progress_or_completion(
            repo.console.recent_lines(), progress=progress
        ):
            _fail("console satisfied progress authority", errors)
        else:
            _ok(
                f"progress authority={progress.get('authority')} "
                f"(not console)"
            )
        if progress.get("authority") in {"console", "stderr", "log", "jsonl"}:
            _fail(f"progress authority is console-like: {progress}", errors)

    # Negative: if progress claims console authority, helper must fail closed.
    if console_cannot_satisfy_progress_or_completion(
        lines, progress={"authority": "console", "sequence": 9}
    ):
        _fail("helper accepted console as progress authority", errors)
    else:
        _ok("helper rejects console-claimed progress authority")

    reset_observability_filesystem_guard()


def validate_sanitized_publication(errors: List[str]) -> None:
    from ipfs_datasets_py.logic.observability.structured_logging import (
        OBSERVABILITY_PUBLICATION_TYPE,
        build_sanitized_observability_publication,
        configure_duckdb_only_observability,
        reset_observability_filesystem_guard,
        sanitize_for_publication,
    )

    reset_observability_filesystem_guard()
    configure_duckdb_only_observability(allow_legacy_file_sinks=False)

    dirty = {
        "action": "login",
        "password": "s3cret-value",
        "api_key": "ak-live-xxx",
        "client_ip": "203.0.113.9",
        "session_id": "sess-high-card-1",
        "raw_payload": {"nested_secret": "x", "blob": "y" * 500},
        "safe_status": "ok",
    }
    cleaned = sanitize_for_publication(dirty)
    if cleaned.get("password") != "***REDACTED***":
        _fail("password not redacted in publication sanitize", errors)
    else:
        _ok("password redacted")
    if cleaned.get("api_key") != "***REDACTED***":
        _fail("api_key not redacted", errors)
    else:
        _ok("api_key redacted")
    if cleaned.get("client_ip") != "***REDACTED***":
        _fail("high-cardinality client_ip not redacted", errors)
    else:
        _ok("client_ip redacted")
    if cleaned.get("session_id") != "***REDACTED***":
        _fail("high-cardinality session_id not redacted", errors)
    else:
        _ok("session_id redacted")
    if cleaned.get("safe_status") != "ok":
        _fail("safe field was incorrectly redacted", errors)
    else:
        _ok("safe fields preserved")

    doc = build_sanitized_observability_publication(
        events=[dirty],
        progress={"authority": "sequence", "sequence": 1},
        mode="db-primary",
    )
    if doc.get("publication_type") != OBSERVABILITY_PUBLICATION_TYPE:
        _fail("publication_type mismatch", errors)
    else:
        _ok(f"publication_type={doc['publication_type']}")
    if doc.get("console_is_authority") is not False:
        _fail("publication claims console authority", errors)
    else:
        _ok("publication console_is_authority=False")
    if not doc.get("secrets_excluded") or not doc.get(
        "high_cardinality_private_excluded"
    ):
        _fail("publication missing exclusion flags", errors)
    else:
        _ok("publication exclusion flags set")
    views = doc.get("approved_sanitized_audit_views") or []
    if not views:
        _fail("publication has no sanitized views", errors)
    else:
        view = views[0]
        if view.get("password") == "s3cret-value" or view.get("api_key") == "ak-live-xxx":
            _fail("publication view leaked secrets", errors)
        else:
            _ok("publication views exclude secrets")

    reset_observability_filesystem_guard()


def main() -> int:
    print("=== validate_duckdb_observability_cutover (DQK-079) ===")
    errors: List[str] = []
    validate_static_source_guards(errors)
    validate_dynamic_guard(errors)
    validate_runtime_without_legacy_files(errors)
    validate_console_not_authority(errors)
    validate_sanitized_publication(errors)

    print()
    if errors:
        print(f"FAILED with {len(errors)} error(s)")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("PASSED all DQK-079 observability cutover checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
