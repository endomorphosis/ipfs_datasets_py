"""Hermetic tests for safe DuckDB MCP query/export tools (DQK-043).

Acceptance coverage:

* Endpoints cannot bypass the query registry
* Cancellation and bounded pagination work
* Errors do not leak secrets, raw SQL, or tokens

Also covers explain, export digests, status handles, capability/snapshot
binding, and import-time inertness (no duckdb import at module load).
"""

from __future__ import annotations

import builtins
import importlib
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

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

import pytest

from ipfs_datasets_py.duckdb_control.contracts import SnapshotId
from ipfs_datasets_py.duckdb_control import query_registry as qr
from ipfs_datasets_py.mcp_server.tools import duckdb_query_tools as dqt


TENANT = "tenant:alpha"
OTHER_TENANT = "tenant:beta"
FIXED_CLOCK = "2026-08-10T12:00:00Z"
SNAPSHOT = "snap-query-001"


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _snapshot(value: str = SNAPSHOT) -> SnapshotId:
    return SnapshotId(value=value, store_generation=1)


def _template(
    *,
    template_id: str = "publication.list_records",
    budget: qr.QueryBudget | None = None,
) -> qr.QueryTemplate:
    return qr.QueryTemplate(
        template_id=template_id,
        version=1,
        sql=(
            "SELECT tenant_id, record_id, status, updated_at "
            "FROM publication_records WHERE tenant_id = ? LIMIT ?"
        ),
        parameter_schema=qr.ParameterSchema(
            schema_version=1,
            parameters=(
                qr.ParameterSpec(
                    name="tenant_id",
                    param_type=qr.ParameterType.TENANT_ID,
                    required=True,
                ),
                qr.ParameterSpec(
                    name="row_limit",
                    param_type=qr.ParameterType.INTEGER,
                    required=False,
                    default=10,
                ),
            ),
        ),
        column_policy=qr.ColumnPolicy(
            {
                "tenant_id": qr.ColumnClassification.PUBLIC,
                "record_id": qr.ColumnClassification.PUBLIC,
                "status": qr.ColumnClassification.PUBLIC,
                "updated_at": qr.ColumnClassification.PUBLIC,
            }
        ),
        budget=budget or qr.DEFAULT_UNTRUSTED_QUERY_BUDGET,
        allowed_trust=frozenset(
            {qr.TrustClass.TRUSTED, qr.TrustClass.UNTRUSTED}
        ),
        description="test list records",
        domains=("publication",),
    )


class FakeBackend:
    def __init__(self, rows: Sequence[Mapping[str, Any]] | None = None) -> None:
        self.rows = list(rows or [])
        self.calls: list[tuple[str, Sequence[Any] | None]] = []

    def execute(
        self, sql: str, parameters: Sequence[Any] | None = None
    ) -> Sequence[Mapping[str, Any]]:
        self.calls.append((sql, parameters))
        return list(self.rows)


def _sample_rows(n: int = 5) -> list[dict[str, Any]]:
    return [
        {
            "tenant_id": TENANT,
            "record_id": f"r{i:03d}",
            "status": "ok",
            "updated_at": FIXED_CLOCK,
        }
        for i in range(n)
    ]


def _gateway(
    *,
    rows: Sequence[Mapping[str, Any]] | None = None,
    include_builtins: bool = False,
) -> tuple[dqt.DuckDBQueryGateway, FakeBackend]:
    registry = qr.open_default_registry(include_builtins=include_builtins)
    template = _template()
    if template.template_id in registry:
        registry.register(template, replace=True)
    else:
        registry.register(template)
    backend = FakeBackend(rows=rows if rows is not None else _sample_rows(5))
    executor = qr.QueryExecutor(
        registry,
        backend=backend,
        audit_log=qr.AuditLog(),
        clock=lambda: FIXED_CLOCK,
    )
    gateway = dqt.DuckDBQueryGateway(
        registry,
        executor=executor,
        clock=lambda: FIXED_CLOCK,
        page_token_secret=b"test-secret-key-32-bytes-long!!",
    )
    return gateway, backend


# ---------------------------------------------------------------------------
# Import-time safety
# ---------------------------------------------------------------------------


def test_module_import_is_side_effect_free(monkeypatch: pytest.MonkeyPatch) -> None:
    forbidden = {"duckdb", "duckdb.experimental"}
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        root = name.split(".", 1)[0]
        if root in forbidden or name in forbidden:
            raise AssertionError(f"import of {name!r} is forbidden at module import")
        return real_import(name, globals, locals, fromlist, level)

    sys.modules.pop("ipfs_datasets_py.mcp_server.tools.duckdb_query_tools", None)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    reloaded = importlib.import_module(
        "ipfs_datasets_py.mcp_server.tools.duckdb_query_tools"
    )
    assert reloaded.QUERY_TOOLS_SCHEMA.endswith("@1")
    assert "duckdb" not in sys.modules or not hasattr(
        sys.modules.get("duckdb", object()), "_forbidden"
    )
    sys.modules["ipfs_datasets_py.mcp_server.tools.duckdb_query_tools"] = reloaded
    monkeypatch.setattr(builtins, "__import__", real_import)


# ---------------------------------------------------------------------------
# Registry bypass denial
# ---------------------------------------------------------------------------


def test_query_rejects_raw_sql_argument() -> None:
    gateway, _ = _gateway()
    with pytest.raises(dqt.QueryToolsError) as exc:
        gateway.query(
            "publication.list_records",
            {"tenant_id": TENANT, "row_limit": 2},
            snapshot_id=_snapshot(),
            tenant_id=TENANT,
            sql="SELECT * FROM secrets",
        )
    assert exc.value.reason_code == "query.sql_surface_denied"
    public = dqt.sanitize_public_error(exc.value)
    assert "SELECT" not in public["error"]
    assert "secrets" not in public["error"].lower()


def test_mcp_query_rejects_raw_sql_without_raising() -> None:
    gateway, _ = _gateway()
    result = dqt.duckdb_query(
        "publication.list_records",
        {"tenant_id": TENANT},
        snapshot_id=SNAPSHOT,
        tenant_id=TENANT,
        sql="DROP TABLE users",
        gateway=gateway,
    )
    assert result["status"] == "error"
    assert result["reason_code"] == "query.sql_surface_denied"
    blob = str(result)
    assert "DROP" not in blob
    assert "users" not in blob or "request denied" in result["error"]


def test_query_rejects_sql_smuggled_as_parameter_key() -> None:
    gateway, _ = _gateway()
    with pytest.raises(dqt.QueryToolsError) as exc:
        gateway.query(
            "publication.list_records",
            {"tenant_id": TENANT, "sql": "SELECT password FROM t"},
            snapshot_id=_snapshot(),
            tenant_id=TENANT,
        )
    assert exc.value.reason_code == "query.sql_surface_denied"


def test_unknown_template_is_denied() -> None:
    gateway, _ = _gateway()
    result = dqt.duckdb_query(
        "not.a.real.template",
        {"tenant_id": TENANT},
        snapshot_id=SNAPSHOT,
        tenant_id=TENANT,
        gateway=gateway,
    )
    assert result["status"] == "error"
    assert result["reason_code"] == "query.unknown_template"


def test_explain_also_denies_arbitrary_sql() -> None:
    gateway, _ = _gateway()
    result = dqt.duckdb_explain(
        "publication.list_records",
        {"tenant_id": TENANT},
        snapshot_id=SNAPSHOT,
        tenant_id=TENANT,
        sql="ATTACH 'evil.db'",
        gateway=gateway,
    )
    assert result["status"] == "error"
    assert result["reason_code"] == "query.sql_surface_denied"
    assert "ATTACH" not in result["error"]
    assert "evil" not in result["error"]


# ---------------------------------------------------------------------------
# Happy path: query, explain, list, capability/snapshot binding
# ---------------------------------------------------------------------------


def test_query_returns_rows_bound_to_snapshot_and_capabilities() -> None:
    gateway, backend = _gateway(rows=_sample_rows(3))
    result = gateway.query(
        "publication.list_records",
        {"tenant_id": TENANT, "row_limit": 3},
        snapshot_id=_snapshot(),
        tenant_id=TENANT,
        page_size=10,
    )
    assert result["status"] == "ok"
    assert result["operation"] == "query"
    assert result["template_id"] == "publication.list_records"
    assert result["snapshot"]["value"] == SNAPSHOT
    assert result["tenant_id"] == TENANT
    assert result["row_count"] == 3
    assert len(result["rows"]) == 3
    assert result["capabilities"]["duckdb"] == "1.5.5"
    assert "receipt" in result
    assert result["receipt"]["parameters_digest"].startswith("sha256:")
    assert result["receipt"]["snapshot"]["value"] == SNAPSHOT
    # Backend received allowlisted SQL only via registry (not caller SQL).
    assert len(backend.calls) == 1
    assert "publication_records" in backend.calls[0][0]
    # Public surface never includes template SQL body verbatim for secrets.
    assert "private_key" not in str(result)


def test_explain_omits_raw_sql_and_bind_values() -> None:
    gateway, _ = _gateway()
    result = gateway.explain(
        "publication.list_records",
        {"tenant_id": TENANT, "row_limit": 5},
        snapshot_id=_snapshot(),
        tenant_id=TENANT,
    )
    assert result["status"] == "ok"
    assert result["operation"] == "explain"
    assert result["template_id"] == "publication.list_records"
    assert result["bind_value_count"] >= 1
    assert "sql" not in result or result.get("sql") in (None, "")
    assert "bind_values" not in result
    redacted = result["sql_redacted"]
    assert redacted
    assert "SELECT" not in redacted or "***REDACTED***" in redacted
    assert "publication_records" not in redacted
    assert result["capabilities"]["duckdb"] == "1.5.5"
    assert result["snapshot"]["value"] == SNAPSHOT


def test_list_templates_filters_by_trust() -> None:
    gateway, _ = _gateway(include_builtins=True)
    # Register trusted-only template.
    gateway.registry.register(
        qr.QueryTemplate(
            template_id="control.only_trusted",
            version=1,
            sql="SELECT tenant_id, task_id FROM control_tasks WHERE tenant_id = ?",
            parameter_schema=qr.ParameterSchema(
                schema_version=1,
                parameters=(
                    qr.ParameterSpec(
                        name="tenant_id",
                        param_type=qr.ParameterType.TENANT_ID,
                        required=True,
                    ),
                ),
            ),
            column_policy=qr.ColumnPolicy(
                {
                    "tenant_id": qr.ColumnClassification.PUBLIC,
                    "task_id": qr.ColumnClassification.PUBLIC,
                }
            ),
            allowed_trust=frozenset({qr.TrustClass.TRUSTED}),
            description="trusted only",
            domains=("control",),
        ),
        replace=True,
    )
    untrusted = gateway.list_templates(trust="untrusted")
    trusted = gateway.list_templates(trust="trusted")
    untrusted_ids = {t["template_id"] for t in untrusted["templates"]}
    trusted_ids = {t["template_id"] for t in trusted["templates"]}
    assert "control.only_trusted" not in untrusted_ids
    assert "control.only_trusted" in trusted_ids
    # No SQL bodies in list surface.
    for item in trusted["templates"]:
        assert "sql" not in item


def test_capability_pin_mismatch_fails_closed() -> None:
    gateway, _ = _gateway()
    with pytest.raises(dqt.QueryToolsError) as exc:
        gateway.query(
            "publication.list_records",
            {"tenant_id": TENANT},
            snapshot_id=_snapshot(),
            tenant_id=TENANT,
            require_duckdb_version="9.9.9",
        )
    assert exc.value.reason_code == "query_tools.capability_mismatch"


# ---------------------------------------------------------------------------
# Cancellation + pagination
# ---------------------------------------------------------------------------


def test_bounded_pagination_and_page_token() -> None:
    rows = _sample_rows(7)
    gateway, _ = _gateway(rows=rows)
    first = gateway.query(
        "publication.list_records",
        {"tenant_id": TENANT, "row_limit": 100},
        snapshot_id=_snapshot(),
        tenant_id=TENANT,
        page_size=3,
    )
    assert first["status"] == "ok"
    assert first["row_count"] == 3
    assert first["total_row_count"] == 7
    assert first["has_more"] is True
    assert first["next_page_token"]
    handle_id = first["handle_id"]

    second = gateway.page(handle_id, first["next_page_token"])
    assert second["status"] == "ok"
    assert second["operation"] == "page"
    assert second["offset"] == 3
    assert second["row_count"] == 3
    assert second["has_more"] is True

    third = gateway.page(handle_id, second["next_page_token"])
    assert third["row_count"] == 1
    assert third["has_more"] is False
    assert third["next_page_token"] is None

    # All record ids unique across pages.
    seen = {r["record_id"] for r in first["rows"] + second["rows"] + third["rows"]}
    assert len(seen) == 7


def test_page_token_cannot_be_forged_across_handles() -> None:
    gateway, _ = _gateway(rows=_sample_rows(5))
    a = gateway.query(
        "publication.list_records",
        {"tenant_id": TENANT, "row_limit": 10},
        snapshot_id=_snapshot(),
        tenant_id=TENANT,
        page_size=2,
    )
    b = gateway.query(
        "publication.list_records",
        {"tenant_id": TENANT, "row_limit": 10},
        snapshot_id=_snapshot(),
        tenant_id=TENANT,
        page_size=2,
    )
    # Using A's token with B's handle must fail.
    with pytest.raises(dqt.QueryToolsError) as exc:
        gateway.page(b["handle_id"], a["next_page_token"])
    assert exc.value.reason_code == "query_tools.invalid_page_token"


def test_page_size_hard_cap() -> None:
    gateway, _ = _gateway()
    with pytest.raises(dqt.QueryToolsError) as exc:
        gateway.query(
            "publication.list_records",
            {"tenant_id": TENANT},
            snapshot_id=_snapshot(),
            tenant_id=TENANT,
            page_size=dqt.MAX_PAGE_SIZE + 1,
        )
    assert exc.value.reason_code == "query_tools.invalid_page_size"


def test_cancellation_before_execution() -> None:
    gateway, _ = _gateway(rows=_sample_rows(10))
    token = qr.CancellationToken()
    token.cancel("client_abort")
    result = gateway.query(
        "publication.list_records",
        {"tenant_id": TENANT, "row_limit": 10},
        snapshot_id=_snapshot(),
        tenant_id=TENANT,
        cancellation=token,
    )
    # Cancelled before/during yields cancelled handle status.
    assert result["handle_status"] == "cancelled"
    assert result.get("status") in {"ok", "error"}


def test_cancel_handle_is_idempotent() -> None:
    gateway, _ = _gateway(rows=_sample_rows(3))
    result = gateway.query(
        "publication.list_records",
        {"tenant_id": TENANT},
        snapshot_id=_snapshot(),
        tenant_id=TENANT,
    )
    handle_id = result["handle_id"]
    first = gateway.cancel(handle_id, reason="user_cancel")
    assert first["status"] == "ok"
    assert first["cancelled"] is True
    second = gateway.cancel(handle_id, reason="user_cancel")
    assert second["status"] == "ok"
    assert second["cancelled"] is True
    assert second["idempotent_replay"] is True

    status = gateway.status(handle_id)
    assert status["status"] == "ok"
    assert status["handle_id"] == handle_id
    assert status["cancelled"] is True


def test_cancel_unknown_handle() -> None:
    gateway, _ = _gateway()
    result = dqt.duckdb_query_cancel("qh-" + "0" * 32, gateway=gateway)
    assert result["status"] == "error"
    assert result["reason_code"] == "query_tools.unknown_handle"


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def test_export_returns_digests_not_sql_or_payload() -> None:
    gateway, _ = _gateway(rows=_sample_rows(2))
    result = gateway.export(
        "publication.list_records",
        {"tenant_id": TENANT, "row_limit": 2},
        snapshot_id=_snapshot(),
        tenant_id=TENANT,
        format="json",
    )
    assert result["status"] == "ok"
    assert result["operation"] == "export"
    export = result["export"]
    assert export["content_digest"].startswith("sha256:")
    assert export["root_cid"]
    assert export["row_count"] == 2
    assert export["read_only"] is True
    assert export["non_authoritative"] is True
    assert export["mutated_source"] is False
    blob = str(result)
    assert "SELECT" not in blob
    assert "payload" not in export
    assert "private_key" not in blob
    assert result["capabilities"]["duckdb"] == "1.5.5"


def test_export_rejects_raw_sql() -> None:
    gateway, _ = _gateway()
    result = dqt.duckdb_export(
        "publication.list_records",
        {"tenant_id": TENANT},
        snapshot_id=SNAPSHOT,
        tenant_id=TENANT,
        sql="COPY secrets TO 'out.csv'",
        gateway=gateway,
    )
    assert result["status"] == "error"
    assert result["reason_code"] == "query.sql_surface_denied"
    assert "COPY" not in result["error"]
    assert "secrets" not in result["error"]


# ---------------------------------------------------------------------------
# Error sanitization
# ---------------------------------------------------------------------------


def test_sanitize_strips_tokens_sql_and_paths() -> None:
    cases = [
        "password=hunter2 token=abc123",
        "SELECT * FROM users WHERE token = 'quack_token_secret'",
        "failed opening /var/lib/duckdb/control.duckdb",
        "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.aaa.bbb",
        "s3://bucket/secret-path/key",
    ]
    for raw in cases:
        public = dqt.sanitize_public_error(raw)
        assert public["status"] == "error"
        text = public["error"].lower()
        assert "hunter2" not in text
        assert "eyj" not in text
        assert "select" not in text
        assert "/var/lib" not in text
        assert "s3://" not in text
        assert "quack_token_secret" not in text


def test_mcp_tools_surface_stable_error_codes() -> None:
    gateway, _ = _gateway()
    missing = dqt.duckdb_query(gateway=gateway)
    assert missing["status"] == "error"
    assert missing["reason_code"] == "query_tools.missing_template_id"

    no_snap = dqt.duckdb_query(
        "publication.list_records",
        {"tenant_id": TENANT},
        tenant_id=TENANT,
        gateway=gateway,
    )
    assert no_snap["status"] == "error"
    assert no_snap["reason_code"] == "query_tools.missing_snapshot"


def test_tenant_policy_violation_is_safe() -> None:
    gateway, _ = _gateway()
    result = dqt.duckdb_query(
        "publication.list_records",
        {"tenant_id": OTHER_TENANT},
        snapshot_id=SNAPSHOT,
        tenant_id=TENANT,
        gateway=gateway,
    )
    assert result["status"] == "error"
    assert result["reason_code"] == "query.tenant_policy_violation"
    assert OTHER_TENANT not in result["error"] or result["error"] == (
        "tenant policy violation"
    )


# ---------------------------------------------------------------------------
# Status + default gateway wiring
# ---------------------------------------------------------------------------


def test_status_after_query() -> None:
    gateway, _ = _gateway(rows=_sample_rows(1))
    q = gateway.query(
        "publication.list_records",
        {"tenant_id": TENANT},
        snapshot_id=_snapshot(),
        tenant_id=TENANT,
    )
    st = dqt.duckdb_query_status(q["handle_id"], gateway=gateway)
    assert st["status"] == "ok"
    assert st["operation"] == "status"
    assert st["handle_status"] == "succeeded"
    assert st["template_id"] == "publication.list_records"
    assert st["snapshot"]["value"] == SNAPSHOT


def test_set_default_gateway_used_by_mcp_entrypoints() -> None:
    gateway, _ = _gateway(rows=_sample_rows(1))
    dqt.set_default_gateway(gateway)
    try:
        result = dqt.duckdb_list_templates(trust="untrusted")
        assert result["status"] == "ok"
        assert result["count"] >= 1
        ids = {t["template_id"] for t in result["templates"]}
        assert "publication.list_records" in ids
    finally:
        dqt.set_default_gateway(None)


def test_redact_helpers_never_echo_secrets() -> None:
    from ipfs_datasets_py.duckdb_control.quack_security import (
        redact_sql,
        redact_token,
    )

    assert redact_token("super-secret-token") == "***REDACTED***"
    redacted = redact_sql("SELECT * FROM t WHERE token = 'x'")
    assert "***REDACTED***" in redacted
    assert "SELECT * FROM t" not in redacted
