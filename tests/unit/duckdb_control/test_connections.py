"""Hermetic unit tests for the DQK-005 connection policy kernel.

Acceptance coverage:

* Control and analytical workloads use separate connection pools/catalogs
* Writers use bounded short transactions
* Untrusted connections cannot autoload extensions or access filesystem/network surfaces

Also covers Quack URI/secrets redaction, statement budgets, read-only analytical
ATTACH, and import-time inertness (no duckdb import at module load).
"""

from __future__ import annotations

import builtins
import sys
from pathlib import Path
from typing import Any

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

from ipfs_datasets_py.duckdb_control import connections as cx


# ---------------------------------------------------------------------------
# Fake DuckDB backend (hermetic; no real duckdb import required)
# ---------------------------------------------------------------------------


class FakeResult:
    def __init__(self, rows: list[tuple[Any, ...]] | None = None) -> None:
        self._rows = rows or []
        self.rowcount = len(self._rows)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)


class FakeConnection:
    """Minimal DuckDB-like handle that records SQL and enforces simple rules."""

    def __init__(self, config: cx.PoolConfig) -> None:
        self.config = config
        self.statements: list[str] = []
        self.closed = False
        self.attached: dict[str, str] = {}
        self.in_tx = False
        self.settings: dict[str, str] = {
            "enable_external_access": "true",
            "autoinstall_known_extensions": "true",
            "autoload_known_extensions": "true",
            "lock_configuration": "false",
            "threads": "1",
            "memory_limit": "256MB",
        }
        self._locked = False

    def execute(self, sql: str, parameters: Any = None) -> FakeResult:  # noqa: ANN401
        if self.closed:
            raise RuntimeError("connection closed")
        text = str(sql).strip()
        self.statements.append(text)
        upper = " ".join(text.upper().split())

        if upper.startswith("SET "):
            if self._locked:
                raise RuntimeError("configuration is locked")
            # SET name=value or SET name='value'
            body = text[4:].strip().rstrip(";")
            if "=" not in body:
                return FakeResult()
            key, _, value = body.partition("=")
            key = key.strip().lower()
            value = value.strip().strip("'\"")
            self.settings[key] = value
            if key == "lock_configuration" and value.lower() in {"true", "1"}:
                self._locked = True
            return FakeResult()

        if upper == "BEGIN TRANSACTION" or upper == "BEGIN":
            self.in_tx = True
            return FakeResult()
        if upper == "COMMIT":
            self.in_tx = False
            return FakeResult()
        if upper == "ROLLBACK":
            self.in_tx = False
            return FakeResult()

        if upper.startswith("ATTACH "):
            # ATTACH 'path' AS alias (READ_ONLY)
            if "READ_ONLY" not in upper:
                raise RuntimeError("attach must be READ_ONLY in fake")
            # naive parse
            if " AS " not in upper:
                raise RuntimeError("attach requires AS alias")
            alias = text.split(" AS ", 1)[1].split("(", 1)[0].strip()
            self.attached[alias] = text
            return FakeResult()

        if upper.startswith("SELECT "):
            return FakeResult([(1,)])

        if upper.startswith(("INSERT ", "UPDATE ", "DELETE ", "CREATE ")):
            return FakeResult()

        return FakeResult()

    def close(self) -> None:
        self.closed = True


def _factory(config: cx.PoolConfig) -> FakeConnection:
    conn = FakeConnection(config)
    # Mirror production factory: apply security SETs immediately.
    cx.apply_security_policy(conn, config.security)
    return conn


def _manager(
    *,
    control_path: str = ":memory:",
    analytical_path: str = ":memory:",
) -> cx.ConnectionManager:
    return cx.ConnectionManager(
        control_path=control_path,
        analytical_path=analytical_path,
        factory=_factory,
    )


# ---------------------------------------------------------------------------
# Import-time safety
# ---------------------------------------------------------------------------


def test_connections_module_import_is_side_effect_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Importing connections must not import duckdb or open resources."""

    forbidden = {"duckdb", "duckdb.experimental"}
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        root = name.split(".", 1)[0]
        if root in forbidden or name in forbidden:
            raise AssertionError(f"import of {name!r} is forbidden at module import")
        return real_import(name, globals, locals, fromlist, level)

    sys.modules.pop("ipfs_datasets_py.duckdb_control.connections", None)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    import importlib

    mod = importlib.import_module("ipfs_datasets_py.duckdb_control.connections")
    assert mod.CONNECTION_POLICY_SCHEMA.startswith("ipfs_datasets_py/")
    assert "duckdb" not in sys.modules


# ---------------------------------------------------------------------------
# Workload isolation: separate pools / catalogs
# ---------------------------------------------------------------------------


def test_control_and_analytical_use_separate_pools_and_catalogs() -> None:
    mgr = _manager(control_path="/tmp/control.duckdb", analytical_path="/tmp/analytical.duckdb")
    try:
        stats = mgr.ensure_isolated_pools()
        control = mgr.pool_for(cx.WorkloadKind.CONTROL, read_write=False)
        writer = mgr.pool_for(cx.WorkloadKind.CONTROL, read_write=True)
        analytical = mgr.pool_for(cx.WorkloadKind.ANALYTICAL)

        assert control is not analytical
        assert writer is not analytical
        assert control is not writer
        assert control.catalog_name == "control"
        assert analytical.catalog_name == "analytical"
        assert control.catalog_name != analytical.catalog_name
        assert control.config.primary_path != analytical.config.primary_path
        assert stats["control"]["workload"] == "control"
        assert stats["analytical"]["workload"] == "analytical"
        assert control.config.access_mode is cx.AccessMode.READ_ONLY
        assert writer.config.access_mode is cx.AccessMode.READ_WRITE
        assert analytical.config.access_mode is cx.AccessMode.READ_ONLY
    finally:
        mgr.close()


def test_cannot_release_across_workload_pools() -> None:
    mgr = _manager()
    try:
        control = mgr.pool_for(cx.WorkloadKind.CONTROL)
        analytical = mgr.pool_for(cx.WorkloadKind.ANALYTICAL)
        conn = control.acquire()
        with pytest.raises(cx.ConnectionError, match="cannot release"):
            analytical.release(conn)
        control.release(conn)
    finally:
        mgr.close()


def test_analytical_pool_rejects_read_write_config() -> None:
    with pytest.raises(cx.ConnectionError, match="read-only"):
        cx.default_pool_config(cx.WorkloadKind.ANALYTICAL, read_write=True)
    with pytest.raises(cx.ConnectionError, match="control workload"):
        mgr = _manager()
        try:
            mgr.pool_for(cx.WorkloadKind.ANALYTICAL, read_write=True)
        finally:
            mgr.close()


# ---------------------------------------------------------------------------
# Writers: bounded short transactions
# ---------------------------------------------------------------------------


def test_writer_uses_bounded_short_transaction() -> None:
    mgr = _manager()
    try:
        with mgr.short_writer_transaction() as conn:
            assert conn.workload is cx.WorkloadKind.CONTROL
            assert conn.access_mode is cx.AccessMode.READ_WRITE
            assert conn.in_transaction is True
            assert conn.budget.max_transaction_ms == cx.DEFAULT_WRITER_TRANSACTION_MS
            conn.execute("INSERT INTO tasks VALUES (1)")
            raw = conn.raw
            assert isinstance(raw, FakeConnection)
            assert raw.in_tx is True
        # After context: committed and released.
        assert conn.closed is True
    finally:
        mgr.close()


def test_writer_transaction_rolls_back_on_error() -> None:
    mgr = _manager()
    try:
        with pytest.raises(RuntimeError, match="boom"):
            with mgr.short_writer_transaction() as conn:
                raw = conn.raw
                assert isinstance(raw, FakeConnection)
                conn.execute("INSERT INTO tasks VALUES (1)")
                raise RuntimeError("boom")
        # Connection closed; last SQL should include ROLLBACK.
        assert any("ROLLBACK" in s.upper() for s in raw.statements)
    finally:
        mgr.close()


def test_writer_transaction_budget_enforced() -> None:
    budget = cx.StatementBudget(
        max_statements=32,
        max_rows=1000,
        max_bytes=1_000_000,
        max_duration_ms=60_000,
        max_transaction_ms=1,  # 1 ms — essentially immediate
    )
    config = cx.PoolConfig(
        workload=cx.WorkloadKind.CONTROL,
        access_mode=cx.AccessMode.READ_WRITE,
        trust=cx.TrustLevel.TRUSTED,
        budget=budget,
        security=cx.default_security_policy(cx.WorkloadKind.CONTROL),
        primary_path=":memory:",
        catalog_name="control",
        max_size=2,
        max_idle=1,
    )
    pool = cx.ConnectionPool(config, factory=_factory)
    conn = pool.acquire()
    try:
        conn.begin()
        # Force the transaction clock into the past.
        assert conn._meter.transaction_started_monotonic is not None  # noqa: SLF001
        conn._meter.transaction_started_monotonic -= 1.0  # noqa: SLF001
        with pytest.raises(cx.StatementBudgetExceeded, match="transaction budget"):
            conn.execute("INSERT INTO t VALUES (1)")
    finally:
        if conn.in_transaction:
            conn.rollback()
        pool.release(conn)
        pool.close()


def test_bounded_writer_session_requires_control_writer() -> None:
    mgr = _manager()
    try:
        with mgr.reader(cx.WorkloadKind.CONTROL) as conn:
            with pytest.raises(cx.ConnectionError, match="writer connection"):
                cx.BoundedWriterSession(conn)
        with mgr.reader(cx.WorkloadKind.ANALYTICAL) as conn:
            with pytest.raises(cx.ConnectionError, match="writer connection"):
                cx.BoundedWriterSession(conn)
    finally:
        mgr.close()


def test_read_only_session_rejects_mutations() -> None:
    mgr = _manager()
    try:
        with mgr.reader(cx.WorkloadKind.CONTROL) as conn:
            with pytest.raises(cx.ConnectionError, match="read-only"):
                conn.execute("INSERT INTO t VALUES (1)")
            with pytest.raises(cx.ConnectionError, match="read-only|denied|disabled"):
                conn.execute("CREATE TABLE t (id INT)")
    finally:
        mgr.close()


# ---------------------------------------------------------------------------
# Analytical catalogs: read-only attach; isolation rules
# ---------------------------------------------------------------------------


def test_attach_read_only_analytical_catalogs() -> None:
    mgr = _manager()
    try:
        specs = [
            cx.AnalyticalCatalogSpec(
                alias="graph",
                path="/var/lib/catalogs/graph.duckdb",
            ),
            cx.AnalyticalCatalogSpec(
                alias="vector",
                path="/var/lib/catalogs/vector.duckdb",
            ),
        ]
        with mgr.reader(cx.WorkloadKind.ANALYTICAL, catalogs=specs) as conn:
            assert conn.attached_aliases == ("graph", "vector")
            raw = conn.raw
            assert isinstance(raw, FakeConnection)
            assert "graph" in raw.attached
            assert "vector" in raw.attached
            assert all("READ_ONLY" in sql.upper() for sql in raw.attached.values())
            # SELECT still works.
            conn.execute("SELECT 1")
    finally:
        mgr.close()


def test_control_cannot_attach_analytical_catalogs() -> None:
    mgr = _manager()
    try:
        spec = cx.AnalyticalCatalogSpec(alias="graph", path="/tmp/graph.duckdb")
        with pytest.raises(cx.ConnectionError, match="analytical"):
            with mgr.reader(cx.WorkloadKind.CONTROL, catalogs=[spec]):
                pass
    finally:
        mgr.close()


def test_untrusted_cannot_attach_authority_catalogs() -> None:
    mgr = _manager()
    try:
        spec = cx.AnalyticalCatalogSpec(alias="graph", path="/tmp/graph.duckdb")
        with pytest.raises(cx.ConnectionError, match="untrusted|authority"):
            with mgr.reader(cx.WorkloadKind.UNTRUSTED, catalogs=[spec]):
                pass
        with pytest.raises(cx.ConnectionError, match="untrusted|publication|authority"):
            with mgr.reader(cx.WorkloadKind.PUBLICATION, catalogs=[spec]):
                pass
    finally:
        mgr.close()


def test_analytical_catalog_spec_rejects_remote_and_writable() -> None:
    with pytest.raises(cx.ConnectionError, match="remote|URI"):
        cx.AnalyticalCatalogSpec(alias="x", path="s3://bucket/key")
    with pytest.raises(cx.ConnectionError, match="remote|URI"):
        cx.AnalyticalCatalogSpec(alias="x", path="https://example.com/db")
    with pytest.raises(cx.ConnectionError, match="read_only"):
        cx.AnalyticalCatalogSpec(alias="x", path="/tmp/x.duckdb", read_only=False)
    with pytest.raises(cx.ConnectionError, match="alias"):
        cx.AnalyticalCatalogSpec(alias="bad-alias!", path="/tmp/x.duckdb")
    with pytest.raises(cx.ConnectionError, match="control"):
        cx.AnalyticalCatalogSpec(
            alias="x",
            path="/tmp/x.duckdb",
            workload=cx.WorkloadKind.CONTROL,
        )


# ---------------------------------------------------------------------------
# External access / autoload denial (untrusted + all default policies)
# ---------------------------------------------------------------------------


def test_untrusted_cannot_autoload_or_access_external_surfaces() -> None:
    mgr = _manager()
    try:
        with mgr.reader(cx.WorkloadKind.UNTRUSTED) as conn:
            sec = conn.security
            assert sec.enable_external_access is False
            assert sec.autoinstall_known_extensions is False
            assert sec.autoload_known_extensions is False
            assert sec.allow_filesystem is False
            assert sec.allow_network is False
            assert sec.lock_configuration is True
            assert conn.trust is cx.TrustLevel.UNTRUSTED

            raw = conn.raw
            assert isinstance(raw, FakeConnection)
            assert raw.settings["enable_external_access"] == "false"
            assert raw.settings["autoinstall_known_extensions"] == "false"
            assert raw.settings["autoload_known_extensions"] == "false"
            assert raw._locked is True  # noqa: SLF001

            with pytest.raises(cx.ConnectionError, match="extension|denied|disabled"):
                conn.execute("INSTALL httpfs")
            with pytest.raises(cx.ConnectionError, match="extension|denied|disabled"):
                conn.execute("LOAD httpfs")
            with pytest.raises(cx.ConnectionError, match="denied|external|filesystem"):
                conn.execute("COPY t TO 'out.csv'")
            with pytest.raises(cx.ConnectionError, match="denied|external|filesystem"):
                conn.execute("SELECT * FROM read_csv('x.csv')")
            with pytest.raises(cx.ConnectionError, match="locked|SET"):
                conn.execute("SET enable_external_access=true")
    finally:
        mgr.close()


def test_control_and_analytical_also_disable_autoload_by_default() -> None:
    for workload in (cx.WorkloadKind.CONTROL, cx.WorkloadKind.ANALYTICAL):
        policy = cx.default_security_policy(workload)
        assert policy.autoinstall_known_extensions is False
        assert policy.autoload_known_extensions is False
        assert policy.enable_external_access is False
        stmts = cx.security_statements_for(policy)
        assert any("autoinstall_known_extensions=false" in s for s in stmts)
        assert any("autoload_known_extensions=false" in s for s in stmts)
        assert any("enable_external_access=false" in s for s in stmts)
        assert stmts[-1] == "SET lock_configuration=true"


def test_security_policy_for_trust_hardens_untrusted() -> None:
    loose = cx.ConnectionSecurityPolicy(
        enable_external_access=True,
        autoinstall_known_extensions=True,
        autoload_known_extensions=True,
        lock_configuration=False,
        allow_filesystem=True,
        allow_network=True,
    )
    hardened = loose.for_trust(cx.TrustLevel.UNTRUSTED)
    assert hardened.enable_external_access is False
    assert hardened.autoinstall_known_extensions is False
    assert hardened.autoload_known_extensions is False
    assert hardened.lock_configuration is True
    assert hardened.allow_filesystem is False
    assert hardened.allow_network is False


def test_build_duckdb_config_matches_policy() -> None:
    policy = cx.default_security_policy(
        cx.WorkloadKind.UNTRUSTED, trust=cx.TrustLevel.UNTRUSTED
    )
    cfg = cx.build_duckdb_config(policy)
    assert cfg["enable_external_access"] == "false"
    assert cfg["autoinstall_known_extensions"] == "false"
    assert cfg["autoload_known_extensions"] == "false"
    assert "threads" in cfg
    assert "memory_limit" in cfg


# ---------------------------------------------------------------------------
# Statement budgets
# ---------------------------------------------------------------------------


def test_statement_budget_exceeded() -> None:
    budget = cx.StatementBudget(
        max_statements=2,
        max_rows=1000,
        max_bytes=1_000_000,
        max_duration_ms=60_000,
        max_transaction_ms=5_000,
    )
    config = cx.default_pool_config(cx.WorkloadKind.CONTROL)
    config = cx.PoolConfig(
        workload=config.workload,
        max_size=2,
        max_idle=1,
        access_mode=cx.AccessMode.READ_ONLY,
        trust=cx.TrustLevel.TRUSTED,
        budget=budget,
        security=config.security,
        primary_path=":memory:",
        catalog_name="control",
    )
    pool = cx.ConnectionPool(config, factory=_factory)
    try:
        with pool.connection() as conn:
            conn.execute("SELECT 1")
            conn.execute("SELECT 2")
            with pytest.raises(cx.StatementBudgetExceeded, match="statement budget"):
                conn.execute("SELECT 3")
    finally:
        pool.close()


def test_session_duration_budget_exceeded() -> None:
    budget = cx.StatementBudget(
        max_statements=100,
        max_rows=1000,
        max_bytes=1_000_000,
        max_duration_ms=1,
        max_transaction_ms=5_000,
    )
    config = cx.PoolConfig(
        workload=cx.WorkloadKind.CONTROL,
        access_mode=cx.AccessMode.READ_ONLY,
        trust=cx.TrustLevel.TRUSTED,
        budget=budget,
        security=cx.default_security_policy(cx.WorkloadKind.CONTROL),
        primary_path=":memory:",
        catalog_name="control",
        max_size=1,
        max_idle=0,
    )
    pool = cx.ConnectionPool(config, factory=_factory)
    try:
        with pool.connection() as conn:
            conn._meter.started_monotonic -= 1.0  # noqa: SLF001
            with pytest.raises(cx.StatementBudgetExceeded, match="duration budget"):
                conn.execute("SELECT 1")
    finally:
        pool.close()


def test_invalid_budget_rejected() -> None:
    with pytest.raises(cx.ConnectionError):
        cx.StatementBudget(max_statements=0)
    with pytest.raises(cx.ConnectionError):
        cx.StatementBudget(max_rows=-1)


# ---------------------------------------------------------------------------
# Quack URI / secrets handling
# ---------------------------------------------------------------------------


def test_parse_quack_uri_separates_secrets() -> None:
    uri = cx.parse_quack_uri("quack://alice:s3cret-token@127.0.0.1:5433/shard_a")
    assert uri.endpoint.host == "127.0.0.1"
    assert uri.endpoint.port == 5433
    assert uri.endpoint.database == "shard_a"
    assert uri.secrets.token == "s3cret-token"
    assert uri.secrets.username == "alice"
    # Secrets never appear in redacted form.
    redacted = uri.redacted()
    assert "s3cret-token" not in redacted
    assert "alice" not in redacted or "***" in redacted
    assert "127.0.0.1:5433" in redacted
    public = uri.to_dict()
    assert public["secrets"]["token"] == "***"
    assert public["secrets"]["password"] == "***"
    assert "s3cret" not in repr(uri.secrets)
    assert "s3cret" not in str(uri.secrets)


def test_parse_quack_uri_query_token_and_tls() -> None:
    uri = cx.parse_quack_uri("quacks://localhost:9443/pub?token=one-shot")
    assert uri.endpoint.use_tls is True
    assert uri.secrets.token == "one-shot"
    assert "one-shot" not in uri.redacted()
    redacted = cx.redact_quack_uri("quack://u:p@localhost:1/db")
    assert "***@" in redacted
    assert "localhost:1" in redacted
    assert ":p@" not in redacted


def test_parse_quack_uri_rejects_bad_input() -> None:
    with pytest.raises(cx.ConnectionError):
        cx.parse_quack_uri("")
    with pytest.raises(cx.ConnectionError, match="scheme"):
        cx.parse_quack_uri("http://localhost:1/db")
    with pytest.raises(cx.ConnectionError, match="host"):
        cx.parse_quack_uri("quack:///db")
    with pytest.raises(cx.ConnectionError):
        cx.QuackEndpoint(host="", port=1)
    with pytest.raises(cx.ConnectionError):
        cx.QuackEndpoint(host="localhost", port=0)


def test_manager_quack_uri_public_vs_secrets() -> None:
    mgr = _manager()
    try:
        parsed = mgr.set_quack_uri("quack://broker:top-secret@127.0.0.1:5433/control")
        assert parsed.secrets.token == "top-secret"
        public = mgr.quack_endpoint_public()
        assert public is not None
        assert "top-secret" not in str(public)
        assert public["endpoint"]["host"] == "127.0.0.1"
        secrets = mgr.quack_secrets()
        assert secrets is not None
        assert secrets.token == "top-secret"
    finally:
        mgr.close()


# ---------------------------------------------------------------------------
# Pool lifecycle / short-lived connections
# ---------------------------------------------------------------------------


def test_pool_acquire_release_and_stats() -> None:
    config = cx.default_pool_config(cx.WorkloadKind.CONTROL)
    pool = cx.ConnectionPool(config, factory=_factory)
    try:
        c1 = pool.acquire()
        assert pool.checked_out == 1
        pool.release(c1)
        assert pool.checked_out == 0
        assert pool.created_count >= 1
        stats = pool.stats()
        assert stats["workload"] == "control"
        assert stats["closed"] is False
    finally:
        pool.close()
        assert pool.stats()["closed"] is True


def test_pool_max_size_timeout() -> None:
    config = cx.PoolConfig(
        workload=cx.WorkloadKind.CONTROL,
        max_size=1,
        max_idle=0,
        acquire_timeout_ms=20,
        access_mode=cx.AccessMode.READ_ONLY,
        trust=cx.TrustLevel.TRUSTED,
        budget=cx.DEFAULT_CONTROL_BUDGET,
        security=cx.default_security_policy(cx.WorkloadKind.CONTROL),
        primary_path=":memory:",
        catalog_name="control",
    )
    pool = cx.ConnectionPool(config, factory=_factory)
    try:
        held = pool.acquire()
        with pytest.raises(cx.ConnectionError, match="timed out"):
            pool.acquire()
        pool.release(held)
    finally:
        pool.close()


def test_short_lived_reader_context_closes() -> None:
    mgr = _manager()
    try:
        with mgr.reader(cx.WorkloadKind.ANALYTICAL) as conn:
            assert conn.closed is False
            assert conn.workload is cx.WorkloadKind.ANALYTICAL
            snap = conn.usage_snapshot()
            assert snap["workload"] == "analytical"
            assert snap["closed"] is False
        assert conn.closed is True
    finally:
        mgr.close()


def test_manager_close_closes_pools() -> None:
    mgr = _manager()
    control = mgr.pool_for(cx.WorkloadKind.CONTROL)
    mgr.close()
    with pytest.raises(cx.ConnectionError, match="closed"):
        control.acquire()
    with pytest.raises(cx.ConnectionError, match="closed"):
        mgr.pool_for(cx.WorkloadKind.ANALYTICAL)


# ---------------------------------------------------------------------------
# Policy / config validation
# ---------------------------------------------------------------------------


def test_pool_config_rejects_untrusted_writer() -> None:
    with pytest.raises(cx.ConnectionError, match="untrusted|read_write|control"):
        cx.PoolConfig(
            workload=cx.WorkloadKind.CONTROL,
            access_mode=cx.AccessMode.READ_WRITE,
            trust=cx.TrustLevel.UNTRUSTED,
            budget=cx.DEFAULT_CONTROL_BUDGET,
            security=cx.default_security_policy(cx.WorkloadKind.CONTROL),
        )


def test_memory_limit_validation() -> None:
    with pytest.raises(cx.ConnectionError, match="memory_limit"):
        cx.ConnectionSecurityPolicy(memory_limit="lots")
    ok = cx.ConnectionSecurityPolicy(memory_limit="512MB")
    assert ok.memory_limit == "512MB"


def test_schema_constant_stable() -> None:
    assert cx.CONNECTION_POLICY_SCHEMA == (
        "ipfs_datasets_py/duckdb-control-connection-policy@1"
    )


def test_writer_begin_requires_read_write() -> None:
    mgr = _manager()
    try:
        with mgr.reader(cx.WorkloadKind.CONTROL) as conn:
            with pytest.raises(cx.ConnectionError, match="read_write|writer"):
                conn.begin()
    finally:
        mgr.close()
