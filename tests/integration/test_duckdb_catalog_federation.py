"""Integration tests for workload-separated catalog federation (DQK-040).

Acceptance coverage:

* No GRANT-style catalog ACL is assumed
* Untrusted sessions never ATTACH authority catalogs
* Cross-catalog snapshots expose revision bindings
* Analytical cancellation leaves control-plane transactions healthy

Also covers explicit workload routes and sanitized copy-out publications into
a physically separate publication catalog.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any

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

from ipfs_datasets_py.duckdb_control import connections as cx
from ipfs_datasets_py.duckdb_control import federation as fed


# ---------------------------------------------------------------------------
# Fake DuckDB backend (hermetic; no real duckdb required)
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
    """Minimal DuckDB-like handle that records SQL and ATTACH operations."""

    def __init__(self, config: cx.PoolConfig) -> None:
        self.config = config
        self.statements: list[str] = []
        self.closed = False
        self.attached: dict[str, str] = {}
        self.in_tx = False
        self.tables: dict[str, list[tuple[Any, ...]]] = {}
        self.settings: dict[str, str] = {
            "enable_external_access": "true",
            "autoinstall_known_extensions": "true",
            "autoload_known_extensions": "true",
            "lock_configuration": "false",
            "threads": "1",
            "memory_limit": "256MB",
        }
        self._locked = False
        self._query_rows: dict[str, list[tuple[Any, ...]]] = {}

    def execute(self, sql: str, parameters: Any = None) -> FakeResult:
        if self.closed:
            raise RuntimeError("connection closed")
        text = str(sql).strip()
        self.statements.append(text)
        upper = " ".join(text.upper().split())

        if upper.startswith("SET "):
            if self._locked:
                raise RuntimeError("configuration is locked")
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

        if upper in {"BEGIN TRANSACTION", "BEGIN"}:
            self.in_tx = True
            return FakeResult()
        if upper == "COMMIT":
            self.in_tx = False
            return FakeResult()
        if upper == "ROLLBACK":
            self.in_tx = False
            return FakeResult()

        if upper.startswith("ATTACH "):
            if "READ_ONLY" not in upper:
                raise RuntimeError("attach must be READ_ONLY in fake")
            if " AS " not in upper:
                raise RuntimeError("attach requires AS alias")
            alias = text.split(" AS ", 1)[1].split("(", 1)[0].strip()
            self.attached[alias] = text
            return FakeResult()

        if upper.startswith("CREATE TABLE"):
            # CREATE TABLE IF NOT EXISTS name (cols)
            name = text.split("EXISTS", 1)[-1].split("(", 1)[0].strip()
            if name.upper().startswith("TABLE"):
                name = name.split(None, 1)[-1].strip()
            self.tables.setdefault(name, [])
            return FakeResult()

        if upper.startswith("INSERT INTO"):
            # INSERT INTO name (cols) VALUES (...)
            after = text[len("INSERT INTO") :].strip()
            table = after.split(None, 1)[0].strip()
            values = tuple(parameters) if parameters is not None else ()
            self.tables.setdefault(table, []).append(values)
            return FakeResult()

        if upper.startswith("SELECT "):
            # Prefer scripted rows keyed by normalized SQL, else trivial.
            key = " ".join(text.split())
            if key in self._query_rows:
                return FakeResult(self._query_rows[key])
            # Default analytical projection used by copy-out tests.
            if "FROM" in upper and self.attached:
                return FakeResult(
                    [
                        ("graph-node-1", "public-label"),
                        ("graph-node-2", "public-label"),
                    ]
                )
            return FakeResult([(1,)])

        if upper.startswith(("UPDATE ", "DELETE ", "DROP ", "ALTER ")):
            return FakeResult()

        return FakeResult()

    def close(self) -> None:
        self.closed = True


def _factory(config: cx.PoolConfig) -> FakeConnection:
    conn = FakeConnection(config)
    cx.apply_security_policy(conn, config.security)
    return conn


def _manager() -> cx.ConnectionManager:
    return cx.ConnectionManager(
        control_path=":memory:control",
        analytical_path=":memory:analytical",
        publication_path=":memory:publication",
        factory=_factory,
    )


def _broker(
    manager: cx.ConnectionManager | None = None,
) -> tuple[cx.ConnectionManager, fed.TrustedQueryBroker]:
    mgr = manager or _manager()
    broker = fed.TrustedQueryBroker(mgr)
    broker.register_authority_catalog(
        fed.AuthorityCatalog(
            alias="graph",
            path="/var/lib/catalogs/graph.duckdb",
            domain=fed.CatalogDomain.GRAPH,
            revision_id="graph-rev-7",
            store_generation=7,
            schema_checksum=(
                "sha256:" + "ab" * 32
            ),
        )
    )
    broker.register_authority_catalog(
        fed.AuthorityCatalog(
            alias="proof",
            path="/var/lib/catalogs/proof.duckdb",
            domain=fed.CatalogDomain.PROOF,
            revision_id="proof-rev-3",
            store_generation=3,
        )
    )
    broker.register_authority_catalog(
        fed.AuthorityCatalog(
            alias="wallet",
            path="/var/lib/catalogs/wallet.duckdb",
            domain=fed.CatalogDomain.WALLET,
            revision_id="wallet-rev-11",
            store_generation=11,
        )
    )
    return mgr, broker


# ---------------------------------------------------------------------------
# Import-time safety
# ---------------------------------------------------------------------------


def test_federation_module_import_is_side_effect_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins
    import importlib

    forbidden = {"duckdb", "duckdb.experimental"}
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        root = name.split(".", 1)[0]
        if root in forbidden or name in forbidden:
            raise AssertionError(f"import of {name!r} is forbidden at module import")
        return real_import(name, globals, locals, fromlist, level)

    sys.modules.pop("ipfs_datasets_py.duckdb_control.federation", None)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    mod = importlib.import_module("ipfs_datasets_py.duckdb_control.federation")
    assert mod.FEDERATION_SCHEMA.startswith("ipfs_datasets_py/")
    assert "duckdb" not in sys.modules


# ---------------------------------------------------------------------------
# Acceptance: No GRANT-style catalog ACL is assumed
# ---------------------------------------------------------------------------


def test_no_grant_style_catalog_acl_is_assumed() -> None:
    mgr, broker = _broker()
    try:
        broker.assert_no_grant_acl()
        policy = broker.policy.to_dict()
        assert policy["grant_acl_assumed"] is False
        assert policy["isolation_model"] == "physical_workload_routes_and_copy_out"
        assert policy["allow_untrusted_authority_attach"] is False

        # Enabling GRANT ACL assumption fails closed at construction.
        with pytest.raises(fed.FederationError, match="GRANT-style|ACL"):
            fed.FederationPolicy(grant_acl_assumed=True)

        # GRANT/REVOKE SQL is rejected on federated sessions.
        with broker.open_session(
            fed.RouteIntent.ANALYTICAL_FEDERATED_QUERY,
            catalog_aliases=["graph"],
        ) as session:
            with pytest.raises(fed.FederationError, match="GRANT|REVOKE|physical"):
                session.execute("GRANT SELECT ON graph.vertices TO public")
            with pytest.raises(fed.FederationError, match="GRANT|REVOKE|physical"):
                session.execute("REVOKE ALL ON graph.vertices FROM public")

        # Route descriptors never claim a GRANT boundary.
        for route in fed.default_routes().values():
            assert route.to_dict()["grant_acl_assumed"] is False

        assert broker.to_dict()["grant_acl_assumed"] is False
    finally:
        broker.close()
        mgr.close()


def test_source_sql_rejects_grant_and_mutation_surfaces() -> None:
    mgr, broker = _broker()
    try:
        snap = broker.bind_cross_catalog_snapshot(["graph"])
        with pytest.raises(fed.FederationError, match="GRANT|forbids"):
            fed.SanitizedCopyOutSpec(
                publication_id="pub-1",
                target_table="public_nodes",
                columns=(fed.CopyOutColumn("id"),),
                source_sql="SELECT id FROM graph.vertices; GRANT SELECT ON t TO u",
                source_snapshot=snap,
            )
        with pytest.raises(fed.FederationError, match="forbids|ATTACH"):
            fed.SanitizedCopyOutSpec(
                publication_id="pub-1",
                target_table="public_nodes",
                columns=(fed.CopyOutColumn("id"),),
                source_sql="SELECT 1; ATTACH '/secret.duckdb' AS s (READ_ONLY)",
                source_snapshot=snap,
            )
    finally:
        broker.close()
        mgr.close()


# ---------------------------------------------------------------------------
# Acceptance: Untrusted sessions never ATTACH authority catalogs
# ---------------------------------------------------------------------------


def test_untrusted_sessions_never_attach_authority_catalogs() -> None:
    mgr, broker = _broker()
    try:
        for intent in (
            fed.RouteIntent.UNTRUSTED_QUACK_CLIENT,
            fed.RouteIntent.SANITIZED_PUBLICATION,
        ):
            with pytest.raises(
                fed.FederationError, match="cannot ATTACH|untrusted|authority"
            ):
                with broker.open_session(intent, catalog_aliases=["graph"]):
                    pass

        # Control route also refuses analytical authority ATTACH.
        with pytest.raises(fed.FederationError, match="cannot ATTACH|authority"):
            with broker.open_session(
                fed.RouteIntent.CONTROL_HEARTBEAT,
                catalog_aliases=["proof"],
            ):
                pass

        # Direct ConnectionManager path still enforces the same boundary.
        spec = cx.AnalyticalCatalogSpec(
            alias="graph", path="/var/lib/catalogs/graph.duckdb"
        )
        with pytest.raises(cx.ConnectionError, match="untrusted|authority"):
            with mgr.reader(cx.WorkloadKind.UNTRUSTED, catalogs=[spec]):
                pass
        with pytest.raises(cx.ConnectionError, match="untrusted|publication|authority"):
            with mgr.reader(cx.WorkloadKind.PUBLICATION, catalogs=[spec]):
                pass

        # Trusted analytical route is the only path that ATTACHes.
        with broker.open_session(
            fed.RouteIntent.ANALYTICAL_FEDERATED_QUERY,
            catalog_aliases=["graph", "proof"],
        ) as session:
            assert session.route.allow_authority_attach is True
            assert session.route.trust is cx.TrustLevel.TRUSTED
            assert set(session.attached_aliases) == {"graph", "proof"}
            raw = session.connection.raw
            assert isinstance(raw, FakeConnection)
            assert "graph" in raw.attached
            assert "proof" in raw.attached
            assert all("READ_ONLY" in sql.upper() for sql in raw.attached.values())
    finally:
        broker.close()
        mgr.close()


def test_untrusted_route_definition_forbids_authority_attach_flag() -> None:
    with pytest.raises(fed.FederationError, match="untrusted|authority|ATTACH"):
        fed.WorkloadRoute(
            name="bad_untrusted",
            intent=fed.RouteIntent.UNTRUSTED_QUACK_CLIENT,
            workload=cx.WorkloadKind.UNTRUSTED,
            trust=cx.TrustLevel.UNTRUSTED,
            allow_authority_attach=True,
            allowed_domains=frozenset({fed.CatalogDomain.PUBLICATION}),
        )
    with pytest.raises(fed.FederationError, match="publication|untrusted|authority"):
        fed.WorkloadRoute(
            name="bad_pub",
            intent=fed.RouteIntent.SANITIZED_PUBLICATION,
            workload=cx.WorkloadKind.PUBLICATION,
            trust=cx.TrustLevel.UNTRUSTED,
            allow_authority_attach=False,
            allowed_domains=frozenset({fed.CatalogDomain.WALLET}),
        )


# ---------------------------------------------------------------------------
# Acceptance: Cross-catalog snapshots expose revision bindings
# ---------------------------------------------------------------------------


def test_cross_catalog_snapshots_expose_revision_bindings() -> None:
    mgr, broker = _broker()
    try:
        snap = broker.bind_cross_catalog_snapshot(
            ["graph", "proof", "wallet"],
            snapshot_id="snap-cross-1",
        )
        assert snap.snapshot_id == "snap-cross-1"
        assert len(snap.bindings) == 3

        # Revision vector is explicit and audit-visible.
        vector = snap.revision_vector
        assert len(vector) == 3
        by_alias = {m["catalog_alias"]: m for m in vector}
        assert by_alias["graph"]["revision_id"] == "graph-rev-7"
        assert by_alias["graph"]["store_generation"] == 7
        assert by_alias["graph"]["domain"] == "graph"
        assert by_alias["graph"]["schema_checksum"].startswith("sha256:")
        assert by_alias["proof"]["revision_id"] == "proof-rev-3"
        assert by_alias["wallet"]["revision_id"] == "wallet-rev-11"

        payload = snap.to_dict()
        assert payload["schema"] == fed.CROSS_CATALOG_SNAPSHOT_SCHEMA
        assert "revision_bindings" in payload
        assert len(payload["revision_bindings"]) == 3
        assert payload["grant_acl_assumed"] is False
        assert payload["identity_id"].startswith("sha256:")

        # Session-bound snapshot carries the same bindings.
        with broker.open_session(
            fed.RouteIntent.ANALYTICAL_FEDERATED_QUERY,
            catalog_aliases=["graph", "proof"],
        ) as session:
            assert session.snapshot is not None
            assert {b.catalog_alias for b in session.snapshot.bindings} == {
                "graph",
                "proof",
            }
            graph_binding = session.snapshot.binding_for("graph")
            assert graph_binding.revision_id == "graph-rev-7"
            usage = session.usage_snapshot()
            assert usage["snapshot"]["revision_bindings"]
            assert usage["grant_acl_assumed"] is False
    finally:
        broker.close()
        mgr.close()


def test_snapshot_rejects_missing_or_duplicate_bindings() -> None:
    mgr, broker = _broker()
    try:
        with pytest.raises(fed.FederationError, match="at least one"):
            broker.bind_cross_catalog_snapshot([])
        with pytest.raises(fed.FederationError, match="duplicate"):
            broker.bind_cross_catalog_snapshot(["graph", "graph"])
        with pytest.raises(fed.FederationError, match="unknown"):
            broker.bind_cross_catalog_snapshot(["missing"])
    finally:
        broker.close()
        mgr.close()


# ---------------------------------------------------------------------------
# Acceptance: Analytical cancellation leaves control-plane transactions healthy
# ---------------------------------------------------------------------------


def test_analytical_cancellation_leaves_control_transactions_healthy() -> None:
    mgr, broker = _broker()
    try:
        cancel = fed.CancellationToken()
        control_committed = threading.Event()
        control_error: list[BaseException] = []
        analytical_saw_cancel = threading.Event()

        def control_writer() -> None:
            try:
                with broker.control_writer_transaction() as conn:
                    assert conn.workload is cx.WorkloadKind.CONTROL
                    assert conn.in_transaction is True
                    # Hold the writer open while analytical work is cancelled.
                    conn.execute("INSERT INTO heartbeats VALUES (1)")
                    # Wait until analytical side has been cancelled.
                    analytical_saw_cancel.wait(timeout=2.0)
                    # Control transaction must still be able to proceed.
                    conn.execute("INSERT INTO heartbeats VALUES (2)")
                    assert conn.in_transaction is True
                control_committed.set()
            except BaseException as exc:  # noqa: BLE001
                control_error.append(exc)

        writer_thread = threading.Thread(target=control_writer, name="control-writer")
        writer_thread.start()

        # Give the control writer a moment to open its transaction.
        time.sleep(0.05)

        with pytest.raises(fed.FederationError, match="cancelled"):
            with broker.open_session(
                fed.RouteIntent.ANALYTICAL_FEDERATED_QUERY,
                catalog_aliases=["graph", "proof"],
                cancel=cancel,
            ) as session:
                session.execute("SELECT 1")
                cancel.cancel("benchmark-timeout")
                analytical_saw_cancel.set()
                # Next execute must fail closed on cancellation.
                session.execute("SELECT 2")

        writer_thread.join(timeout=3.0)
        assert not writer_thread.is_alive()
        assert control_error == [], f"control writer failed: {control_error!r}"
        assert control_committed.is_set()

        # Control plane remains usable after analytical cancellation.
        health = broker.probe_control_health()
        assert health["healthy"] is True
        assert health["control_transactions_healthy"] is True
        assert health["grant_acl_assumed"] is False
        assert broker.control_transactions_healthy is True

        # A subsequent control mutation still succeeds.
        with broker.control_writer_transaction() as conn:
            conn.execute("INSERT INTO leases VALUES (1)")
            assert conn.workload is cx.WorkloadKind.CONTROL
    finally:
        broker.close()
        mgr.close()


def test_cancel_token_is_session_local() -> None:
    token = fed.CancellationToken()
    assert token.is_cancelled is False
    token.cancel("stop")
    assert token.is_cancelled is True
    assert token.reason == "stop"
    with pytest.raises(fed.FederationError, match="cancelled"):
        token.check()


# ---------------------------------------------------------------------------
# Workload routes + sanitized copy-out
# ---------------------------------------------------------------------------


def test_explicit_workload_routes_cover_all_intents() -> None:
    routes = fed.default_routes()
    assert set(routes) == set(fed.RouteIntent)
    analytical = routes[fed.RouteIntent.ANALYTICAL_FEDERATED_QUERY]
    assert analytical.allow_authority_attach is True
    assert analytical.workload is cx.WorkloadKind.ANALYTICAL
    assert fed.CatalogDomain.CONTROL not in analytical.allowed_domains

    untrusted = routes[fed.RouteIntent.UNTRUSTED_QUACK_CLIENT]
    assert untrusted.allow_authority_attach is False
    assert untrusted.trust is cx.TrustLevel.UNTRUSTED

    resolved = fed.resolve_workload_route("control_heartbeat")
    assert resolved.name == "control_heartbeat"
    with pytest.raises(fed.FederationError, match="unknown"):
        fed.resolve_workload_route("not-a-route")


def test_sanitized_copy_out_publication_never_attaches_authority() -> None:
    mgr, broker = _broker()
    try:
        snap = broker.bind_cross_catalog_snapshot(["graph", "proof"])
        spec = fed.SanitizedCopyOutSpec(
            publication_id="pub-nodes-1",
            target_table="public_nodes",
            columns=(
                fed.CopyOutColumn("node_id"),
                fed.CopyOutColumn("label"),
            ),
            source_sql="SELECT node_id, label FROM graph.vertices",
            source_snapshot=snap,
            max_rows=100,
        )
        # Hermetic path: inject rows so we do not depend on SQL projection shape.
        receipt = broker.publish_sanitized_copy_out(
            spec,
            row_source=[
                ("n1", "alpha"),
                ("n2", "beta"),
            ],
        )
        assert receipt.row_count == 2
        assert receipt.columns == ("node_id", "label")
        assert receipt.non_authoritative is True
        assert receipt.content_digest.startswith("sha256:")
        payload = receipt.to_dict()
        assert payload["authority_catalogs_attached_to_publication"] is False
        assert payload["grant_acl_assumed"] is False
        assert payload["source_snapshot"]["revision_bindings"]

        # Sensitive columns are rejected at spec construction.
        with pytest.raises(fed.FederationError, match="forbidden"):
            fed.CopyOutColumn("private_key")
        with pytest.raises(fed.FederationError, match="forbidden"):
            fed.CopyOutColumn("quack_token")
    finally:
        broker.close()
        mgr.close()


def test_copy_out_detects_revision_drift() -> None:
    mgr, broker = _broker()
    try:
        snap = broker.bind_cross_catalog_snapshot(["graph"])
        broker.update_catalog_revision("graph", revision_id="graph-rev-8")
        spec = fed.SanitizedCopyOutSpec(
            publication_id="pub-drift",
            target_table="public_nodes",
            columns=(fed.CopyOutColumn("id"),),
            source_sql="SELECT id FROM graph.vertices",
            source_snapshot=snap,
        )
        with pytest.raises(fed.FederationError, match="revision drift"):
            broker.publish_sanitized_copy_out(spec, row_source=[("x",)])
    finally:
        broker.close()
        mgr.close()


def test_control_catalog_cannot_be_registered_for_attach_federation() -> None:
    mgr = _manager()
    broker = fed.TrustedQueryBroker(mgr)
    try:
        with pytest.raises(fed.FederationError, match="control catalog"):
            broker.register_authority_catalog(
                fed.AuthorityCatalog(
                    alias="control",
                    path="/var/lib/catalogs/control.duckdb",
                    domain=fed.CatalogDomain.CONTROL,
                    revision_id="ctrl-1",
                )
            )
    finally:
        broker.close()
        mgr.close()


def test_expensive_analytical_scan_uses_separate_pool_from_control() -> None:
    mgr, broker = _broker()
    try:
        control_pool = mgr.pool_for(cx.WorkloadKind.CONTROL)
        analytical_pool = mgr.pool_for(cx.WorkloadKind.ANALYTICAL)
        assert control_pool is not analytical_pool
        assert control_pool.catalog_name != analytical_pool.catalog_name

        with broker.open_session(
            fed.RouteIntent.ANALYTICAL_FEDERATED_QUERY,
            catalog_aliases=["graph"],
        ) as session:
            assert session.connection.workload is cx.WorkloadKind.ANALYTICAL
            session.execute("SELECT * FROM graph.vertices")

        with broker.open_session(fed.RouteIntent.CONTROL_HEARTBEAT) as session:
            assert session.connection.workload is cx.WorkloadKind.CONTROL
            assert session.attached_aliases == ()
            session.execute("SELECT 1")
    finally:
        broker.close()
        mgr.close()


def test_schema_constants_stable() -> None:
    assert fed.FEDERATION_SCHEMA == (
        "ipfs_datasets_py/duckdb-control-catalog-federation@1"
    )
    assert fed.CROSS_CATALOG_SNAPSHOT_SCHEMA.endswith("cross-catalog-snapshot@1")
    assert fed.PUBLICATION_RECEIPT_SCHEMA.endswith("sanitized-publication@1")
