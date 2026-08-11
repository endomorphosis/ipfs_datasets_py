#!/usr/bin/env python3
"""Validate DuckDB-only observability cutover (DQK-079).

Checks:

* Producer modules pass static writer guards (no undeclared mutable file sinks)
* Dynamic guards reject file sinks under export-only / db-primary
* Console cannot claim progress or completion authority
* Sanitized publication views exclude secrets and high-cardinality private keys
* Runtime works with legacy audit/log/metric JSON files absent

Exit codes: 0 = pass, 1 = fail.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ipfs_datasets_py.logic.observability.structured_logging import (  # noqa: E402
    HIGH_CARDINALITY_PRIVATE_KEYS,
    LEGACY_MUTABLE_OBSERVABILITY_FILENAMES,
    OBSERVABILITY_FILE_SINK_OWNER_TASK,
    OBSERVABILITY_FILE_SINK_POLICY_SCHEMA,
    OBSERVABILITY_PRODUCER_MODULE_PATHS,
    ObservabilityConsoleAuthorityError,
    ObservabilityMutableFileSinkError,
    assert_console_not_progress_or_completion_authority,
    assert_mutable_file_sink_allowed,
    duckdb_is_observability_authority,
    legacy_mutable_file_sinks_allowed,
    sanitized_publication_view,
    static_guard_observability_producers,
    static_guard_reject_undeclared_file_sinks,
)


def _configure_export_only() -> Any:
    from ipfs_datasets_py.duckdb_control.authority_transition import AuthorityMode
    from ipfs_datasets_py.duckdb_control.observability_cutover import (
        configure_observability_cutover,
        reset_observability_cutover,
    )

    reset_observability_cutover()
    return configure_observability_cutover(mode=AuthorityMode.EXPORT_ONLY)


def check_static_guards(repo_root: Path) -> Dict[str, Any]:
    report = static_guard_observability_producers(repo_root)
    violations = {k: v for k, v in report.items() if v}
    return {
        "check": "static_writer_guards",
        "ok": not violations,
        "modules_scanned": len(report),
        "violations": violations,
        "paths": list(OBSERVABILITY_PRODUCER_MODULE_PATHS),
    }


def check_dynamic_guards() -> Dict[str, Any]:
    from ipfs_datasets_py.duckdb_control.observability_cutover import (
        reset_observability_cutover,
    )

    repo = _configure_export_only()
    errors: List[str] = []
    try:
        assert legacy_mutable_file_sinks_allowed() is False
        assert duckdb_is_observability_authority() is True
        try:
            assert_mutable_file_sink_allowed("audit.jsonl", kind="audit")
            errors.append("expected ObservabilityMutableFileSinkError for audit.jsonl")
        except ObservabilityMutableFileSinkError:
            pass
        try:
            assert_mutable_file_sink_allowed(
                "metric_snapshot.json", kind="metric_snapshot"
            )
            errors.append(
                "expected ObservabilityMutableFileSinkError for metric_snapshot.json"
            )
        except ObservabilityMutableFileSinkError:
            pass
        try:
            assert_mutable_file_sink_allowed("alert_state.json", kind="alert_state")
            errors.append(
                "expected ObservabilityMutableFileSinkError for alert_state.json"
            )
        except ObservabilityMutableFileSinkError:
            pass
    finally:
        reset_observability_cutover()

    return {
        "check": "dynamic_writer_guards",
        "ok": not errors,
        "errors": errors,
        "mode": "export_only",
        "owner_task": OBSERVABILITY_FILE_SINK_OWNER_TASK,
    }


def check_console_not_authority() -> Dict[str, Any]:
    from ipfs_datasets_py.duckdb_control.observability_cutover import (
        get_observability_cutover,
        reset_observability_cutover,
    )

    repo = _configure_export_only()
    errors: List[str] = []
    try:
        assert repo.console.is_authority is False
        try:
            assert_console_not_progress_or_completion_authority(claim_progress=True)
            errors.append("expected ObservabilityConsoleAuthorityError for progress")
        except ObservabilityConsoleAuthorityError:
            pass
        try:
            assert_console_not_progress_or_completion_authority(claim_completion=True)
            errors.append("expected ObservabilityConsoleAuthorityError for completion")
        except ObservabilityConsoleAuthorityError:
            pass
        # Soft check (no claim) must pass.
        assert_console_not_progress_or_completion_authority()
        live = get_observability_cutover()
        if live is not None and live.console.is_authority:
            errors.append("live console projection claims authority")
    finally:
        reset_observability_cutover()

    return {
        "check": "console_not_authority",
        "ok": not errors,
        "errors": errors,
    }


def check_sanitized_publication() -> Dict[str, Any]:
    dirty = {
        "action": "login",
        "password": "s3cr3t",
        "token": "abc.def.ghi",
        "api_key": "key-123",
        "user_id": "user-999",
        "session_id": "sess-1",
        "client_ip": "10.0.0.1",
        "request_id": "req-1",
        "status": "ok",
        "count": 3,
        "details": {"secret": "nested", "metric": 1},
    }
    clean = sanitized_publication_view(dirty)
    errors: List[str] = []
    for secret_key in ("password", "token", "api_key"):
        if secret_key in clean and clean[secret_key] not in {
            "[REDACTED]",
            "[redacted]",
        }:
            # Key may be stripped entirely or redacted.
            if clean.get(secret_key) == dirty[secret_key]:
                errors.append(f"secret key leaked: {secret_key}")
    for hc in HIGH_CARDINALITY_PRIVATE_KEYS:
        if hc in clean:
            errors.append(f"high-cardinality private key retained: {hc}")
    if "action" not in clean:
        errors.append("expected public field 'action' retained")
    if clean.get("status") != "ok":
        errors.append("expected status retained")

    return {
        "check": "sanitized_publication_view",
        "ok": not errors,
        "errors": errors,
        "sample_keys": sorted(clean.keys()),
    }


def check_runtime_without_legacy_files(tmp_root: Path) -> Dict[str, Any]:
    from ipfs_datasets_py.audit.audit_logger import (
        AuditCategory,
        AuditLevel,
        AuditLogger,
    )
    from ipfs_datasets_py.duckdb_control.authority_transition import AuthorityMode
    from ipfs_datasets_py.duckdb_control.observability_cutover import (
        EventKind,
        configure_observability_cutover,
        reset_observability_cutover,
    )
    from ipfs_datasets_py.duckdb_control.observability_adapters import (
        ObservabilityProducer,
    )
    from ipfs_datasets_py.logic.security import audit_log as logic_audit
    from ipfs_datasets_py.mcp_server.logger import log_mcp_event
    from ipfs_datasets_py.optimizers.graphrag.audit_logger import (
        AuditLogger as GraphAuditLogger,
    )
    from ipfs_datasets_py.optimizers.graphrag.pipeline_json_logger import (
        PipelineJSONLogger,
    )

    empty = tmp_root / "no-legacy"
    empty.mkdir(parents=True, exist_ok=True)
    for name in LEGACY_MUTABLE_OBSERVABILITY_FILENAMES:
        assert not (empty / name).exists()

    reset_observability_cutover()
    repo = configure_observability_cutover(mode=AuthorityMode.DB_PRIMARY)
    errors: List[str] = []
    try:
        # Core audit logger (in-memory handlers only)
        al = AuditLogger()
        al._instance = al  # avoid singleton pollution in repeated runs
        eid = al.log(
            AuditLevel.INFO,
            AuditCategory.SECURITY,
            "dqk079.validate",
            user="validator",
            details={"message": "runtime without files"},
        )
        if not eid:
            errors.append("audit_logger.log returned no event id")

        # Logic security audit (console only under cutover)
        logic_audit.AuditLogger(log_path=str(empty / "audit_log.json"))
        logic_audit.AuditLogger.log_event(
            event_type="validation.probe",
            user_id="validator",
            success=True,
            details={"message": "ok"},
        )

        # GraphRAG audit memory-only
        gal = GraphAuditLogger(
            output_dir=str(empty / "audit_logs"),
            enable_file_logging=True,
        )
        if gal.enable_file_logging:
            errors.append("graphrag file logging should be disabled post-canary")
        gal.log_cycle_start(
            data="probe",
            context=type("C", (), {"data_source": "probe", "domain": "test", "extraction_strategy": "x"})(),
            max_rounds=1,
            convergence_threshold=0.1,
        )

        # Pipeline JSON logger (console)
        plog = PipelineJSONLogger(domain="validation")
        plog._emit_log("validation.probe", {"status": "ok"})

        # MCP logger
        log_mcp_event("validation probe", event_type="mcp.validation")

        # Authority snapshot without JSONL
        snap = repo.open_snapshot()
        if snap.jsonl_scanned:
            errors.append("snapshot scanned JSONL")
        if snap.console_is_authority:
            errors.append("snapshot claims console authority")

        # No legacy files created under empty root
        for name in LEGACY_MUTABLE_OBSERVABILITY_FILENAMES:
            if (empty / name).exists():
                errors.append(f"legacy file created: {name}")
        # GraphRAG should not have created audit_*.jsonl
        audit_logs = empty / "audit_logs"
        if audit_logs.exists():
            for child in audit_logs.iterdir():
                if child.suffix in {".json", ".jsonl"}:
                    errors.append(f"graphrag created file sink: {child.name}")
    finally:
        reset_observability_cutover()

    return {
        "check": "runtime_without_legacy_files",
        "ok": not errors,
        "errors": errors,
        "legacy_filenames": list(LEGACY_MUTABLE_OBSERVABILITY_FILENAMES),
    }


def run_all(repo_root: Path, tmp_root: Path) -> Dict[str, Any]:
    results = [
        check_static_guards(repo_root),
        check_dynamic_guards(),
        check_console_not_authority(),
        check_sanitized_publication(),
        check_runtime_without_legacy_files(tmp_root),
    ]
    ok = all(r.get("ok") for r in results)
    return {
        "schema": OBSERVABILITY_FILE_SINK_POLICY_SCHEMA,
        "owner_task": OBSERVABILITY_FILE_SINK_OWNER_TASK,
        "ok": ok,
        "results": results,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=_REPO_ROOT,
        help="Repository root to scan",
    )
    parser.add_argument(
        "--tmp-root",
        type=Path,
        default=None,
        help="Temporary directory for runtime checks",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON report to stdout",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    import tempfile

    if args.tmp_root is not None:
        tmp_root = args.tmp_root
        tmp_root.mkdir(parents=True, exist_ok=True)
        report = run_all(args.repo_root, tmp_root)
    else:
        with tempfile.TemporaryDirectory(prefix="dqk079-") as td:
            report = run_all(args.repo_root, Path(td))

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        status = "PASS" if report["ok"] else "FAIL"
        print(f"DQK-079 observability cutover validation: {status}")
        for item in report["results"]:
            mark = "ok" if item.get("ok") else "FAIL"
            print(f"  [{mark}] {item.get('check')}")
            if not item.get("ok"):
                if item.get("errors"):
                    for err in item["errors"]:
                        print(f"       - {err}")
                if item.get("violations"):
                    for path, viols in item["violations"].items():
                        for v in viols:
                            print(f"       - {v}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
