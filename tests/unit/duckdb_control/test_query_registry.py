"""Hermetic unit tests for the DQK-041 allowlisted query-template registry.

Acceptance coverage:

* Untrusted callers cannot submit arbitrary SQL
* read_* functions and extension/filesystem/network surfaces are denied
* Receipts identify template, parameters digest, snapshot, policy, and
  resource usage

Also covers versioned parameter schemas, prepared templates, tenant/column
policy, row/byte/time/depth budgets, cancellation, and audit events.
Import-time inertness is verified (no duckdb import at module load).
"""

from __future__ import annotations

import builtins
import importlib
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[3]
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

from ipfs_datasets_py.duckdb_control.contracts import SnapshotId, content_identity
from ipfs_datasets_py.duckdb_control import query_registry as qr


TENANT = "tenant:alpha"
OTHER_TENANT = "tenant:beta"
FIXED_CLOCK = "2026-08-10T12:00:00Z"


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _snapshot(value: str = "snap-control-001") -> SnapshotId:
    return SnapshotId(value=value, store_generation=1)


def _tenant_policy(tenant_id: str = TENANT, **kwargs: Any) -> qr.TenantPolicy:
    return qr.TenantPolicy(tenant_id=tenant_id, **kwargs)


def _simple_template(
    *,
    template_id: str = "publication.list_records",
    sql: str | None = None,
    budget: qr.QueryBudget | None = None,
    allowed_trust: frozenset[qr.TrustClass] | None = None,
    version: int = 1,
) -> qr.QueryTemplate:
    if sql is None:
        sql = (
            "SELECT tenant_id, record_id, status, updated_at "
            "FROM publication_records WHERE tenant_id = ? LIMIT ?"
        )
    return qr.QueryTemplate(
        template_id=template_id,
        version=version,
        sql=sql,
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
        allowed_trust=allowed_trust
        or frozenset({qr.TrustClass.TRUSTED, qr.TrustClass.UNTRUSTED}),
        description="test template",
        domains=("publication",),
    )


class FakeBackend:
    """Hermetic row source that records SQL and never imports duckdb."""

    def __init__(self, rows: Sequence[Mapping[str, Any]] | None = None) -> None:
        self.rows = list(rows or [])
        self.calls: list[tuple[str, Sequence[Any] | None]] = []

    def execute(
        self, sql: str, parameters: Sequence[Any] | None = None
    ) -> Sequence[Mapping[str, Any]]:
        self.calls.append((sql, parameters))
        return list(self.rows)


def _executor(
    *,
    rows: Sequence[Mapping[str, Any]] | None = None,
    include_builtins: bool = False,
    register: Sequence[qr.QueryTemplate] | None = None,
) -> tuple[qr.QueryExecutor, FakeBackend, qr.QueryRegistry]:
    registry = qr.open_default_registry(include_builtins=include_builtins)
    for template in register or (_simple_template(),):
        if template.template_id not in registry:
            registry.register(template)
        else:
            registry.register(template, replace=True)
    backend = FakeBackend(rows=rows)
    executor = qr.QueryExecutor(
        registry,
        backend=backend,
        audit_log=qr.AuditLog(),
        clock=lambda: FIXED_CLOCK,
    )
    return executor, backend, registry


# ---------------------------------------------------------------------------
# Import-time safety
# ---------------------------------------------------------------------------


def test_query_registry_module_import_is_side_effect_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbidden = {"duckdb", "duckdb.experimental"}
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        root = name.split(".", 1)[0]
        if root in forbidden or name in forbidden:
            raise AssertionError(f"import of {name!r} is forbidden at module import")
        return real_import(name, globals, locals, fromlist, level)

    sys.modules.pop("ipfs_datasets_py.duckdb_control.query_registry", None)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    reloaded = importlib.import_module(
        "ipfs_datasets_py.duckdb_control.query_registry"
    )
    assert reloaded.QUERY_REGISTRY_SCHEMA.endswith("@1")
    assert reloaded.QUERY_RECEIPT_SCHEMA.endswith("@1")
    sys.modules["ipfs_datasets_py.duckdb_control.query_registry"] = reloaded
    monkeypatch.setattr(builtins, "__import__", real_import)


# ---------------------------------------------------------------------------
# Arbitrary SQL denial
# ---------------------------------------------------------------------------


def test_untrusted_callers_cannot_submit_arbitrary_sql() -> None:
    executor, _, _ = _executor(rows=[])
    with pytest.raises(qr.SQLSurfaceDenied) as exc:
        executor.execute(
            "publication.list_records",
            {"tenant_id": TENANT, "row_limit": 1},
            trust=qr.TrustClass.UNTRUSTED,
            tenant_policy=_tenant_policy(),
            snapshot=_snapshot(),
            sql="SELECT * FROM secrets",
        )
    assert exc.value.reason_code == "query.sql_surface_denied"
    assert "arbitrary_sql" in str(exc.value)


def test_prepare_rejects_sql_smuggled_as_parameter_key() -> None:
    registry = qr.open_default_registry(include_builtins=False)
    registry.register(_simple_template())
    with pytest.raises(qr.SQLSurfaceDenied):
        registry.prepare(
            "publication.list_records",
            {"tenant_id": TENANT, "sql": "DROP TABLE users"},
            trust=qr.TrustClass.UNTRUSTED,
            tenant_policy=_tenant_policy(),
            snapshot=_snapshot(),
        )


def test_unknown_template_is_rejected() -> None:
    registry = qr.open_default_registry(include_builtins=False)
    with pytest.raises(qr.UnknownTemplateError) as exc:
        registry.get("not.a.template")
    assert exc.value.reason_code == "query.unknown_template"


def test_deny_arbitrary_sql_helper() -> None:
    with pytest.raises(qr.SQLSurfaceDenied):
        qr.deny_arbitrary_sql("SELECT 1", template_id="x")
    with pytest.raises(qr.QueryRegistryError):
        qr.deny_arbitrary_sql(None, template_id=None)


# ---------------------------------------------------------------------------
# Surface denials: read_*, extensions, filesystem, network
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM read_csv('secrets.csv')",
        "SELECT * FROM read_parquet('s3://bucket/a.parquet')",
        "SELECT * FROM read_json_auto('/tmp/x.json')",
        "SELECT * FROM read_blob('file.bin')",
        "INSTALL httpfs",
        "LOAD httpfs",
        "COPY t TO 'out.csv'",
        "ATTACH 'other.db' AS o",
        "SELECT * FROM 'data.parquet'",
        "SELECT * FROM httpfs_list('s3://bucket')",
        "CREATE TABLE t AS SELECT 1",
        "INSERT INTO t VALUES (1)",
        "SELECT 1; SELECT 2",
        "UPDATE t SET a = 1",
        "SELECT * FROM read_csv_auto(?)",
    ],
)
def test_scan_sql_surface_denies_dangerous_forms(sql: str) -> None:
    with pytest.raises(qr.SQLSurfaceDenied):
        qr.scan_sql_surface(sql)


def test_template_registration_rejects_read_star_and_extensions() -> None:
    with pytest.raises(qr.SQLSurfaceDenied):
        qr.QueryTemplate(
            template_id="evil.read_csv",
            version=1,
            sql="SELECT * FROM read_csv('x.csv')",
            parameter_schema=qr.ParameterSchema(schema_version=1, parameters=()),
            column_policy=qr.ColumnPolicy(
                {"x": qr.ColumnClassification.PUBLIC}
            ),
        )
    with pytest.raises(qr.SQLSurfaceDenied):
        _simple_template(sql="LOAD vss; SELECT 1")


def test_safe_select_templates_are_accepted() -> None:
    sql = qr.scan_sql_surface(
        "SELECT tenant_id, record_id FROM publication_records WHERE tenant_id = ?"
    )
    assert sql.startswith("SELECT")
    assert "?" in sql


# ---------------------------------------------------------------------------
# Versioned parameter schemas + prepared templates
# ---------------------------------------------------------------------------


def test_parameter_schema_rejects_unknown_and_wrong_types() -> None:
    schema = qr.ParameterSchema(
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
                default=5,
            ),
        ),
    )
    ok = qr.validate_parameters(schema, {"tenant_id": TENANT})
    assert ok["tenant_id"] == TENANT
    assert ok["row_limit"] == 5

    with pytest.raises(qr.ParameterValidationError):
        qr.validate_parameters(schema, {"tenant_id": TENANT, "extra": 1})
    with pytest.raises(qr.ParameterValidationError):
        qr.validate_parameters(schema, {"tenant_id": 123})
    with pytest.raises(qr.ParameterValidationError):
        qr.validate_parameters(schema, {"row_limit": 1})


def test_digest_parameters_is_deterministic() -> None:
    a = qr.digest_parameters({"tenant_id": TENANT, "row_limit": 3})
    b = qr.digest_parameters({"row_limit": 3, "tenant_id": TENANT})
    assert a == b
    assert a.startswith("sha256:")
    assert a != qr.digest_parameters({"tenant_id": TENANT, "row_limit": 4})


def test_prepare_binds_validated_parameters() -> None:
    registry = qr.open_default_registry(include_builtins=False)
    registry.register(_simple_template())
    prepared = registry.prepare(
        "publication.list_records",
        {"tenant_id": TENANT, "row_limit": 7},
        trust=qr.TrustClass.UNTRUSTED,
        tenant_policy=_tenant_policy(),
        snapshot=_snapshot(),
    )
    assert prepared.template.template_id == "publication.list_records"
    assert prepared.parameters["row_limit"] == 7
    assert prepared.bind_values[0] == TENANT
    assert prepared.bind_values[1] == 7
    assert prepared.parameters_digest == qr.digest_parameters(
        {"tenant_id": TENANT, "row_limit": 7}
    )


def test_trusted_only_template_denies_untrusted() -> None:
    registry = qr.open_default_registry(include_builtins=False)
    registry.register(
        _simple_template(
            template_id="control.task_status",
            sql=(
                "SELECT tenant_id, record_id, status, updated_at "
                "FROM control_tasks WHERE tenant_id = ? LIMIT ?"
            ),
            allowed_trust=frozenset({qr.TrustClass.TRUSTED}),
        )
    )
    with pytest.raises(qr.QueryRegistryError):
        registry.prepare(
            "control.task_status",
            {"tenant_id": TENANT, "row_limit": 1},
            trust=qr.TrustClass.UNTRUSTED,
            tenant_policy=_tenant_policy(),
            snapshot=_snapshot(),
        )


# ---------------------------------------------------------------------------
# Tenant / column policy
# ---------------------------------------------------------------------------


def test_tenant_policy_rejects_mismatched_parameter() -> None:
    registry = qr.open_default_registry(include_builtins=False)
    registry.register(_simple_template())
    with pytest.raises(qr.TenantPolicyViolation):
        registry.prepare(
            "publication.list_records",
            {"tenant_id": OTHER_TENANT, "row_limit": 1},
            trust=qr.TrustClass.UNTRUSTED,
            tenant_policy=_tenant_policy(TENANT),
            snapshot=_snapshot(),
        )


def test_tenant_policy_rejects_mismatched_result_row() -> None:
    rows = [
        {
            "tenant_id": OTHER_TENANT,
            "record_id": "r1",
            "status": "ok",
            "updated_at": FIXED_CLOCK,
        }
    ]
    executor, _, _ = _executor(rows=rows)
    with pytest.raises(qr.TenantPolicyViolation):
        executor.execute(
            "publication.list_records",
            {"tenant_id": TENANT, "row_limit": 10},
            trust=qr.TrustClass.UNTRUSTED,
            tenant_policy=_tenant_policy(),
            snapshot=_snapshot(),
        )


def test_column_policy_rejects_secret_and_sensitive_names() -> None:
    with pytest.raises(qr.ColumnPolicyError):
        qr.ColumnPolicy(
            {"private_key": qr.ColumnClassification.PUBLIC}
        )
    with pytest.raises(qr.ColumnPolicyError):
        qr.ColumnPolicy(
            {"token": qr.ColumnClassification.PUBLIC}
        )
    with pytest.raises(qr.ColumnPolicyError):
        qr.ColumnPolicy(
            {"note": qr.ColumnClassification.SECRET}
        )


def test_column_policy_projects_and_redacts() -> None:
    policy = qr.ColumnPolicy(
        {
            "tenant_id": qr.ColumnClassification.PUBLIC,
            "note": qr.ColumnClassification.REDACTED,
        }
    )
    projected = policy.project_row(
        {"tenant_id": TENANT, "note": "secret-ish", "extra": "drop-me"}
    )
    assert projected["tenant_id"] == TENANT
    assert projected["note"] == "***"
    assert "extra" not in projected

    with pytest.raises(qr.ColumnPolicyError):
        policy.project_row({"tenant_id": TENANT, "private_key": "x"})


# ---------------------------------------------------------------------------
# Budgets: row / byte / time / depth
# ---------------------------------------------------------------------------


def test_row_budget_truncates_results() -> None:
    rows = [
        {
            "tenant_id": TENANT,
            "record_id": f"r{i}",
            "status": "ok",
            "updated_at": FIXED_CLOCK,
        }
        for i in range(10)
    ]
    template = _simple_template(
        budget=qr.QueryBudget(
            max_rows=3,
            max_bytes=1_000_000,
            max_duration_ms=5_000,
            max_depth=4,
            max_parameter_bytes=16_384,
        )
    )
    executor, _, _ = _executor(rows=rows, register=[template])
    result = executor.execute(
        "publication.list_records",
        {"tenant_id": TENANT, "row_limit": 10},
        trust=qr.TrustClass.UNTRUSTED,
        tenant_policy=_tenant_policy(),
        snapshot=_snapshot(),
    )
    assert result.receipt.row_count == 3
    assert result.receipt.truncated is True
    assert result.receipt.status in {
        qr.QueryStatus.TRUNCATED,
        qr.QueryStatus.SUCCEEDED,
    }
    assert result.receipt.resource_usage.rows == 3
    assert len(result.rows) == 3


def test_parameter_byte_budget_fails_closed() -> None:
    template = _simple_template(
        budget=qr.QueryBudget(
            max_rows=10,
            max_bytes=10_000,
            max_duration_ms=5_000,
            max_depth=4,
            max_parameter_bytes=8,
        )
    )
    registry = qr.open_default_registry(include_builtins=False)
    registry.register(template)
    with pytest.raises(qr.QueryBudgetExceeded) as exc:
        registry.prepare(
            "publication.list_records",
            {"tenant_id": TENANT, "row_limit": 1},
            trust=qr.TrustClass.UNTRUSTED,
            tenant_policy=_tenant_policy(),
            snapshot=_snapshot(),
        )
    assert exc.value.kind == "parameter_bytes"


def test_depth_budget_enforced() -> None:
    executor, _, _ = _executor(rows=[])
    with pytest.raises(qr.QueryBudgetExceeded) as exc:
        executor.execute(
            "publication.list_records",
            {"tenant_id": TENANT, "row_limit": 1},
            trust=qr.TrustClass.UNTRUSTED,
            tenant_policy=_tenant_policy(),
            snapshot=_snapshot(),
            max_depth=100,
        )
    assert exc.value.kind == "depth"


def test_untrusted_budget_is_capped() -> None:
    loose = _simple_template(
        budget=qr.QueryBudget(
            max_rows=500_000,
            max_bytes=100 * 1024 * 1024,
            max_duration_ms=120_000,
            max_depth=32,
            max_parameter_bytes=100_000,
        )
    )
    registry = qr.open_default_registry(include_builtins=False)
    registry.register(loose)
    effective = registry.effective_budget(loose, qr.TrustClass.UNTRUSTED)
    assert effective.max_rows <= qr.DEFAULT_UNTRUSTED_QUERY_BUDGET.max_rows
    assert effective.max_duration_ms <= qr.DEFAULT_UNTRUSTED_QUERY_BUDGET.max_duration_ms
    trusted = registry.effective_budget(loose, qr.TrustClass.TRUSTED)
    assert trusted.max_rows == 500_000


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


def test_cancellation_before_execution() -> None:
    token = qr.CancellationToken()
    token.cancel("deadline")
    executor, _, _ = _executor(rows=[])
    with pytest.raises(qr.QueryCancelled) as exc:
        executor.execute(
            "publication.list_records",
            {"tenant_id": TENANT, "row_limit": 1},
            trust=qr.TrustClass.UNTRUSTED,
            tenant_policy=_tenant_policy(),
            snapshot=_snapshot(),
            cancellation=token,
        )
    assert "deadline" in str(exc.value)


def test_cancellation_during_row_iteration() -> None:
    token = qr.CancellationToken()
    rows = [
        {
            "tenant_id": TENANT,
            "record_id": f"r{i}",
            "status": "ok",
            "updated_at": FIXED_CLOCK,
        }
        for i in range(5)
    ]

    def row_source(prepared, meter, cancellation):  # noqa: ANN001
        token.cancel("mid-flight")
        return rows

    executor, _, _ = _executor(rows=rows)
    result = executor.execute(
        "publication.list_records",
        {"tenant_id": TENANT, "row_limit": 10},
        trust=qr.TrustClass.UNTRUSTED,
        tenant_policy=_tenant_policy(),
        snapshot=_snapshot(),
        cancellation=token,
        row_source=row_source,
    )
    assert result.receipt.status is qr.QueryStatus.CANCELLED
    assert result.receipt.resource_usage is not None


# ---------------------------------------------------------------------------
# Receipts + audit
# ---------------------------------------------------------------------------


def test_receipt_identifies_template_params_snapshot_policy_and_usage() -> None:
    rows = [
        {
            "tenant_id": TENANT,
            "record_id": "r1",
            "status": "ok",
            "updated_at": FIXED_CLOCK,
        },
        {
            "tenant_id": TENANT,
            "record_id": "r2",
            "status": "ok",
            "updated_at": FIXED_CLOCK,
        },
    ]
    executor, backend, registry = _executor(rows=rows)
    policy = _tenant_policy()
    snap = _snapshot("snap-abc")
    params = {"tenant_id": TENANT, "row_limit": 2}
    result = executor.execute(
        "publication.list_records",
        params,
        trust=qr.TrustClass.UNTRUSTED,
        tenant_policy=policy,
        snapshot=snap,
    )

    receipt = result.receipt
    assert receipt.template_id == "publication.list_records"
    assert receipt.template_version == 1
    assert receipt.parameters_digest == qr.digest_parameters(
        {"tenant_id": TENANT, "row_limit": 2}
    )
    assert receipt.snapshot.value == "snap-abc"
    assert receipt.policy_id == policy.policy_id
    assert receipt.tenant_id == TENANT
    assert receipt.resource_usage.rows == 2
    assert receipt.resource_usage.bytes >= 0
    assert receipt.resource_usage.duration_ms >= 0
    assert receipt.resource_usage.parameter_bytes > 0
    assert receipt.budget.max_rows >= 1
    assert receipt.column_policy_identity
    assert receipt.parameter_schema_identity
    assert receipt.identity_id.startswith("sha256:")
    assert receipt.to_dict()["schema"] == qr.QUERY_RECEIPT_SCHEMA

    # Deterministic identity for identical logical fields (receipt_id differs).
    assert len(result.rows) == 2
    assert backend.calls, "backend must receive prepared SQL"
    sql, bind = backend.calls[0]
    assert "READ_" not in sql.upper()
    assert "INSTALL" not in sql.upper()
    assert bind == (TENANT, 2)

    # Audit trail records the same binding fields.
    events = executor.audit_log.list_events()
    assert len(events) == 1
    event = events[0]
    assert event.template_id == receipt.template_id
    assert event.parameters_digest == receipt.parameters_digest
    assert event.snapshot_id == snap.value
    assert event.policy_id == policy.policy_id
    assert event.resource_usage is not None
    assert event.resource_usage.rows == 2


def test_receipt_identity_stable_for_same_payload() -> None:
    usage = qr.ResourceUsage(rows=1, bytes=10, duration_ms=2, depth=0, parameter_bytes=5)
    budget = qr.DEFAULT_UNTRUSTED_QUERY_BUDGET
    snap = _snapshot()
    base = dict(
        receipt_id="receipt-fixed",
        template_id="publication.list_records",
        template_version=1,
        template_identity="sha256:" + "ab" * 32,
        parameters_digest="sha256:" + "cd" * 32,
        snapshot=snap,
        policy_id="sha256:" + "ef" * 32,
        tenant_id=TENANT,
        trust=qr.TrustClass.UNTRUSTED,
        status=qr.QueryStatus.SUCCEEDED,
        resource_usage=usage,
        budget=budget,
        column_policy_identity="sha256:" + "11" * 32,
        parameter_schema_identity="sha256:" + "22" * 32,
        row_count=1,
        truncated=False,
        created_at=FIXED_CLOCK,
        domains=("publication",),
    )
    r1 = qr.QueryReceipt(**base)
    r2 = qr.QueryReceipt(**base)
    assert r1.identity_id == r2.identity_id
    assert r1.to_dict()["identity_id"] == r1.identity_id


def test_denied_prepare_is_audited() -> None:
    executor, _, _ = _executor(rows=[])
    with pytest.raises(qr.UnknownTemplateError):
        executor.execute(
            "missing.template",
            {"tenant_id": TENANT},
            trust=qr.TrustClass.UNTRUSTED,
            tenant_policy=_tenant_policy(),
            snapshot=_snapshot(),
        )
    events = executor.audit_log.list_events()
    assert len(events) == 1
    assert events[0].status == qr.QueryStatus.DENIED.value


# ---------------------------------------------------------------------------
# Builtins / registry surface
# ---------------------------------------------------------------------------


def test_default_registry_includes_builtins() -> None:
    registry = qr.open_default_registry(include_builtins=True)
    templates = registry.list_templates()
    assert "publication.list_records" in templates
    assert "publication.health_probe" in templates
    assert "control.task_status" in templates
    # Untrusted may not invoke control.task_status
    with pytest.raises(qr.QueryRegistryError):
        registry.prepare(
            "control.task_status",
            {"tenant_id": TENANT, "task_id": "t1"},
            trust=qr.TrustClass.UNTRUSTED,
            tenant_policy=_tenant_policy(),
            snapshot=_snapshot(),
        )
    prepared = registry.prepare(
        "control.task_status",
        {"tenant_id": TENANT, "task_id": "t1"},
        trust=qr.TrustClass.TRUSTED,
        tenant_policy=_tenant_policy(),
        snapshot=_snapshot(),
    )
    assert prepared.bind_values == (TENANT, "t1")


def test_template_identity_changes_with_sql_or_schema() -> None:
    a = _simple_template(version=1)
    b = _simple_template(version=2)
    assert a.identity_id != b.identity_id
    c = _simple_template(
        sql=(
            "SELECT tenant_id, record_id, status, updated_at "
            "FROM publication_records WHERE tenant_id = ?"
        )
    )
    assert a.identity_id != c.identity_id


def test_schema_constants_are_versioned() -> None:
    assert qr.QUERY_REGISTRY_SCHEMA.endswith("@1")
    assert qr.QUERY_RECEIPT_SCHEMA.endswith("@1")
    assert qr.QUERY_AUDIT_SCHEMA.endswith("@1")
    assert qr.PARAMETER_SCHEMA_SCHEMA.endswith("@1")


def test_parameter_schema_identity_is_content_addressed() -> None:
    schema = qr.ParameterSchema(
        schema_version=1,
        parameters=(
            qr.ParameterSpec(
                name="tenant_id",
                param_type=qr.ParameterType.TENANT_ID,
                required=True,
            ),
        ),
    )
    assert schema.identity_id == content_identity(schema.to_dict())
