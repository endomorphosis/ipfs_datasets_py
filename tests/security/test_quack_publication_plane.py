"""Hermetic security tests for DQK-058 sanitized Quack publication plane.

Acceptance coverage:

* Sensitive/internal tables and wallet raw columns are physically absent
* The broker retains authority tokens and clients receive no writer credential
* ATTACH, COPY, INSTALL, LOAD, CREATE SECRET, read_* and HTTP/S3 access fail
* Killing or overloading Quack cannot block authority writers
* Quack never opens or ATTACHes control, proof, graph-writer, AST-writer, or
  wallet authority databases

Importing the module under test must not import duckdb or open network resources.
"""

from __future__ import annotations

import builtins
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ipfs_datasets_py.duckdb_control import publication as pub
from ipfs_datasets_py.duckdb_control import quack_security as qs


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_PUBLICATION_PATH = "/var/lib/publication/sanitized_read_models.duckdb"
_NOW_MS = 1_700_000_000_000


def _fence(*, fence_id: str = "fence-1", generation: int = 1) -> pub.FenceToken:
    return pub.FenceToken(
        fence_id=fence_id,
        generation=generation,
        expires_at_ms=_NOW_MS + 60_000,
        nonce="a" * 32,
    )


def _binding(
    domain: str = "graph",
    revision_id: str = "graph-rev-1",
) -> pub.RevisionBinding:
    return pub.RevisionBinding(
        source_domain=domain,
        revision_id=revision_id,
        store_generation=0,
        schema_checksum="sha256:" + ("ab" * 32),
    )


def _spec(
    *,
    table_name: str = "public_nodes",
    columns: tuple[str, ...] = ("node_id", "label"),
    read_model_id: str = "rm-nodes-1",
) -> pub.ReadModelSpec:
    return pub.ReadModelSpec(
        read_model_id=read_model_id,
        table_name=table_name,
        columns=tuple(pub.AllowlistedColumn(name=c) for c in columns),
        revision_bindings=(_binding(),),
        fence=_fence(),
        max_rows=1000,
        description="sanitized public nodes",
    )


def _plane(
    *,
    path: str = _PUBLICATION_PATH,
    vault: pub.AuthorityTokenVault | None = None,
) -> pub.PublicationPlane:
    return pub.PublicationPlane(
        path,
        vault=vault,
        clock=lambda: datetime(2024, 1, 1, tzinfo=timezone.utc),
        clock_ms=lambda: _NOW_MS,
    )


def _writer(
    *,
    writer_id: str = "writer-control-1",
    role: str = "control",
    path: str = "/var/lib/authority/control.duckdb",
) -> pub.AuthorityWriterHandle:
    return pub.AuthorityWriterHandle(
        writer_id=writer_id,
        role=role,
        os_identity_label=f"authority-writer-{role}",
        process_fence_id=f"writerfence_{role}_1",
        database_path=path,
    )


# ---------------------------------------------------------------------------
# Import-time safety
# ---------------------------------------------------------------------------


def test_publication_module_import_is_side_effect_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbidden = {"duckdb", "duckdb.experimental"}
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        root = name.split(".", 1)[0]
        if root in forbidden or name in forbidden:
            raise AssertionError(f"import of {name!r} is forbidden at module import")
        return real_import(name, globals, locals, fromlist, level)

    sys.modules.pop("ipfs_datasets_py.duckdb_control.publication", None)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    import importlib

    mod = importlib.import_module("ipfs_datasets_py.duckdb_control.publication")
    assert mod.PUBLICATION_PLANE_SCHEMA.startswith("ipfs_datasets_py/")
    assert "control" in mod.AUTHORITY_DATABASE_ROLES
    assert "wallet" in mod.AUTHORITY_DATABASE_ROLES


# ---------------------------------------------------------------------------
# Sensitive/internal tables and wallet raw columns physically absent
# ---------------------------------------------------------------------------


def test_sensitive_internal_tables_and_wallet_raw_columns_physically_absent() -> None:
    plane = _plane()
    try:
        receipt = plane.materialize_read_model(
            _spec(),
            rows=[("n1", "alpha"), ("n2", "beta")],
            now_ms=_NOW_MS,
        )
        assert receipt.row_count == 2
        assert receipt.authority_catalogs_attached is False
        plane.assert_sensitive_surfaces_absent()

        # Forbidden tables rejected at spec construction.
        for bad_table in (
            "wallet_raw",
            "private_keys",
            "internal_leases",
            "quack_tokens",
            "graph_writer_wal",
            "secrets",
        ):
            with pytest.raises(pub.SensitiveSurfaceError):
                _spec(table_name=bad_table, read_model_id=f"rm-{bad_table}")

        # Wallet raw / sensitive columns rejected at column construction.
        for bad_col in (
            "private_key",
            "wallet_secret",
            "raw_payload",
            "mnemonic",
            "seed_phrase",
            "quack_token",
            "encryption_key",
            "signing_key",
        ):
            with pytest.raises(pub.SensitiveSurfaceError):
                pub.AllowlistedColumn(name=bad_col)

        # Physical presence checks after materialize.
        assert "wallet_raw" not in plane.list_tables()
        assert "private_keys" not in plane.list_tables()
        table = plane._db.get_table("public_nodes")  # noqa: SLF001
        assert table is not None
        for col in table.columns:
            assert not pub.is_wallet_raw_column(col)
            assert not pub.is_sensitive_column(col)
    finally:
        plane.close()


def test_forbidden_table_markers_caught() -> None:
    assert pub.is_forbidden_publication_table("internal_meta")
    assert pub.is_forbidden_publication_table("wallet_raw_payloads")
    assert pub.is_forbidden_publication_table("foo_private")
    assert not pub.is_forbidden_publication_table("public_nodes")
    assert not pub.is_forbidden_publication_table("publication_records")


# ---------------------------------------------------------------------------
# Broker retains authority tokens; clients get no writer credential
# ---------------------------------------------------------------------------


def test_broker_retains_authority_tokens_clients_receive_no_writer_credential() -> None:
    vault = pub.AuthorityTokenVault(clock_ms=lambda: _NOW_MS)
    vault.retain_authority_token("control", "authority-control-token-secret-001")
    vault.retain_authority_token("proof", "authority-proof-token-secret-002")
    vault.retain_authority_token("graph-writer", "authority-graph-writer-token-003")
    vault.retain_authority_token("ast-writer", "authority-ast-writer-token-004")
    vault.retain_authority_token("wallet", "authority-wallet-token-secret-005")
    vault.retain_writer_token("broker-writer-token-super-secret")

    plane = _plane(vault=vault)
    try:
        plane.materialize_read_model(
            _spec(),
            rows=[("n1", "alpha")],
            now_ms=_NOW_MS,
        )
        # Broker can still peek tokens (authority retained).
        assert vault.has_authority_token("control")
        assert vault.peek_authority_token_for_broker("control").startswith("authority-")
        assert vault.peek_writer_token_for_broker() == "broker-writer-token-super-secret"
        public_vault = vault.to_public_dict()
        assert public_vault["writer_token_retained"] is True
        assert public_vault["tokens_exposed_to_clients"] is False
        assert set(public_vault["authority_roles_retained"]) == {
            "control",
            "proof",
            "graph-writer",
            "ast-writer",
            "wallet",
        }

        cred = plane.issue_client_credential()
        assert cred.is_writer is False
        assert cred.carries_authority_token is False
        assert cred.access_mode == "read_only"
        client_view = cred.to_public_dict()
        assert vault.client_receives_no_writer_credential(client_view)
        assert client_view["is_writer"] is False
        assert client_view["writer_credential"] is False
        assert client_view["carries_authority_token"] is False
        # Authority / writer secrets must not appear in the public view.
        blob = repr(client_view)
        assert "authority-control-token" not in blob
        assert "broker-writer-token" not in blob

        # Cannot construct a writer client credential.
        with pytest.raises(pub.CredentialError, match="writer"):
            pub.ClientReadCredential(
                credential_id="bad",
                secret="x" * 32,
                is_writer=True,
            )
        with pytest.raises(pub.CredentialError, match="authority"):
            pub.ClientReadCredential(
                credential_id="bad2",
                secret="y" * 32,
                carries_authority_token=True,
            )
        with pytest.raises(pub.CredentialError, match="read_only"):
            pub.ClientReadCredential(
                credential_id="bad3",
                secret="z" * 32,
                access_mode="read_write",
            )

        session = plane.open_client_session(cred)
        assert session.is_writer is False
        assert session.carries_authority_token is False
        session_blob = repr(session.to_dict())
        assert "authority-control-token" not in session_blob
        assert "broker-writer-token" not in session_blob
        session.close()
    finally:
        plane.close()


# ---------------------------------------------------------------------------
# ATTACH, COPY, INSTALL, LOAD, CREATE SECRET, read_*, HTTP/S3 fail
# ---------------------------------------------------------------------------


def test_forbidden_client_sql_surfaces_fail() -> None:
    plane = _plane()
    try:
        plane.materialize_read_model(
            _spec(),
            rows=[("n1", "alpha")],
            now_ms=_NOW_MS,
        )
        cred = plane.issue_client_credential()
        session = plane.open_client_session(cred)
        try:
            forbidden_statements = [
                "ATTACH '/var/lib/authority/control.duckdb' AS control (READ_ONLY)",
                "ATTACH '/tmp/x.duckdb' AS x",
                "COPY public_nodes TO 'out.csv'",
                "INSTALL httpfs",
                "LOAD httpfs",
                "LOAD ducklake",
                "CREATE SECRET s3_secret (TYPE S3, KEY_ID 'x', SECRET 'y')",
                "CREATE OR REPLACE SECRET mysecret (TYPE S3)",
                "SELECT * FROM read_csv('evil.csv')",
                "SELECT * FROM read_parquet('s3://bucket/key')",
                "SELECT * FROM read_json('/tmp/x.json')",
                "SELECT * FROM read_blob('/etc/passwd')",
                "SELECT * FROM read_text('/etc/shadow')",
                "SELECT * FROM 'https://evil.example/data.parquet'",
                "SELECT * FROM 's3://bucket/object'",
                "SELECT * FROM 'http://evil.example/x'",
                "COPY (SELECT 1) TO 's3://bucket/out'",
            ]
            for sql in forbidden_statements:
                with pytest.raises(pub.ClientSqlRejected):
                    session.execute(sql)

            # Allowlisted SELECT works.
            rows = session.execute("SELECT node_id, label FROM public_nodes LIMIT 10")
            assert rows == [("n1", "alpha")]
        finally:
            session.close()
    finally:
        plane.close()


def test_reject_client_sql_covers_closed_denylist() -> None:
    for surface in (
        "ATTACH 'x' AS y",
        "COPY t TO 'f'",
        "INSTALL foo",
        "LOAD bar",
        "CREATE SECRET s (TYPE S3)",
        "SELECT * FROM read_csv_auto('f')",
        "SELECT * FROM 'https://example/x'",
        "SELECT * FROM 's3://b/k'",
    ):
        with pytest.raises(pub.ClientSqlRejected):
            pub.reject_client_sql(surface)


# ---------------------------------------------------------------------------
# Killing or overloading Quack cannot block authority writers
# ---------------------------------------------------------------------------


def test_killing_or_overloading_quack_cannot_block_authority_writers() -> None:
    plane = _plane()
    try:
        for role, path in (
            ("control", "/var/lib/authority/control.duckdb"),
            ("proof", "/var/lib/authority/proof.duckdb"),
            ("graph-writer", "/var/lib/authority/graph-writer.duckdb"),
            ("ast-writer", "/var/lib/authority/ast-writer.duckdb"),
            ("wallet", "/var/lib/authority/wallet.duckdb"),
        ):
            plane.register_authority_writer(
                _writer(
                    writer_id=f"writer-{role}",
                    role=role,
                    path=path,
                )
            )

        assert plane.authority_writers_unblocked_when_quack_dead() is True

        plane.overload_quack_process()
        assert plane.authority_writers_unblocked_when_quack_dead() is True

        plane.kill_quack_process()
        assert plane.authority_writers_unblocked_when_quack_dead() is True

        digest = "sha256:" + ("cd" * 32)
        result = plane.simulate_authority_write_while_quack_killed(
            "writer-control",
            payload_digest=digest,
        )
        assert result["completed"] is True
        assert result["blocked_by_quack"] is False
        assert result["quack_alive"] is False
        assert result["shared_process_with_quack"] is False

        # Shared OS identity with Quack is rejected at registration.
        with pytest.raises(pub.ProcessIsolationError, match="OS identity"):
            plane.register_authority_writer(
                pub.AuthorityWriterHandle(
                    writer_id="bad-shared-identity",
                    role="control",
                    os_identity_label=plane.quack_os_identity_label,
                    process_fence_id="writerfence_other",
                    database_path="/var/lib/authority/control2.duckdb",
                )
            )

        # Shared process fence rejected.
        with pytest.raises(pub.ProcessIsolationError, match="process fence"):
            plane.register_authority_writer(
                pub.AuthorityWriterHandle(
                    writer_id="bad-shared-fence",
                    role="proof",
                    os_identity_label="authority-writer-proof-b",
                    process_fence_id=plane.quack_process_fence_id,
                    database_path="/var/lib/authority/proof2.duckdb",
                )
            )

        # Shared publication DB path rejected.
        with pytest.raises(pub.ProcessIsolationError, match="publication database"):
            plane.register_authority_writer(
                pub.AuthorityWriterHandle(
                    writer_id="bad-shared-path",
                    role="wallet",
                    os_identity_label="authority-writer-wallet-b",
                    process_fence_id="writerfence_wallet_b",
                    database_path=plane.publication_path,
                )
            )
    finally:
        plane.close()


def test_policy_forbids_sharing_process_with_authority_writers() -> None:
    with pytest.raises(pub.ProcessIsolationError):
        pub.PublicationPlanePolicy(share_process_with_authority_writers=True)
    with pytest.raises(pub.AuthorityExposureError):
        pub.PublicationPlanePolicy(allow_authority_attach_on_quack=True)
    with pytest.raises(pub.CredentialError):
        pub.PublicationPlanePolicy(allow_writer_credential_to_clients=True)


# ---------------------------------------------------------------------------
# Quack never opens or ATTACHes authority databases
# ---------------------------------------------------------------------------


def test_quack_never_opens_or_attaches_authority_databases() -> None:
    plane = _plane()
    try:
        plane.materialize_read_model(
            _spec(),
            rows=[("n1", "alpha")],
            now_ms=_NOW_MS,
        )
        opened = plane._db.opened_paths()  # noqa: SLF001
        assert opened == (_PUBLICATION_PATH,)
        assert plane._db.attached_aliases() == {}  # noqa: SLF001

        # Direct path assertions.
        for authority_path in (
            "/var/lib/authority/control.duckdb",
            "/data/proof.duckdb",
            "/srv/graph-writer/catalog.duckdb",
            "/srv/ast-writer/store.duckdb",
            "/secrets/wallet.duckdb",
            "/opt/wallet_authority/db.duckdb",
        ):
            with pytest.raises(pub.AuthorityExposureError):
                pub.assert_no_authority_paths(authority_path)

        # Publication path itself is fine.
        pub.assert_no_authority_paths(_PUBLICATION_PATH)

        # ATTACH attempt on the publication state fails closed.
        with pytest.raises(pub.ClientSqlRejected):
            plane._db.attempt_attach(  # noqa: SLF001
                "/var/lib/authority/control.duckdb", "control"
            )

        # Client session open records only the publication path.
        cred = plane.issue_client_credential()
        session = plane.open_client_session(cred)
        try:
            info = session.to_dict()
            assert info["authority_databases_opened"] is False
            assert all(
                role not in p
                for p in info["opened_paths"]
                for role in (
                    "control.duckdb",
                    "proof.duckdb",
                    "graph-writer",
                    "ast-writer",
                    "wallet.duckdb",
                )
            )
            with pytest.raises(pub.ClientSqlRejected):
                session.execute(
                    "ATTACH '/var/lib/authority/wallet.duckdb' AS wallet (READ_ONLY)"
                )
        finally:
            session.close()

        plane_dict = plane.to_dict()
        assert plane_dict["authority_databases_opened_by_quack"] is False
        assert plane_dict["grant_acl_assumed"] is False
    finally:
        plane.close()


def test_publication_db_path_cannot_be_authority_role() -> None:
    for bad in (
        "/var/lib/control.duckdb",
        "/data/proof.duckdb",
        "/x/graph-writer/y.duckdb",
        "/x/ast_writer/z.duckdb",
        "/wallet.duckdb",
    ):
        with pytest.raises(pub.AuthorityExposureError):
            pub.PublicationDatabaseState(bad)
        with pytest.raises(pub.AuthorityExposureError):
            pub.PublicationPlane(bad)


def test_remote_uri_publication_path_rejected() -> None:
    for bad in (
        "s3://bucket/pub.duckdb",
        "https://example/pub.duckdb",
        "http://example/pub.duckdb",
    ):
        with pytest.raises(pub.AuthorityExposureError):
            pub.PublicationDatabaseState(bad)


# ---------------------------------------------------------------------------
# Revision-bound + fenced materialization
# ---------------------------------------------------------------------------


def test_materialization_is_revision_bound_and_fenced() -> None:
    plane = _plane()
    try:
        with pytest.raises(pub.PublicationError, match="revision binding"):
            pub.ReadModelSpec(
                read_model_id="rm-norev",
                table_name="public_nodes",
                columns=(pub.AllowlistedColumn("id"),),
                revision_bindings=(),
                fence=_fence(),
            )

        expired = pub.FenceToken(
            fence_id="fence-expired",
            generation=1,
            expires_at_ms=_NOW_MS - 1,
            nonce="b" * 32,
        )
        spec = pub.ReadModelSpec(
            read_model_id="rm-expired",
            table_name="public_nodes",
            columns=(pub.AllowlistedColumn("id"),),
            revision_bindings=(_binding(),),
            fence=expired,
        )
        with pytest.raises(pub.PublicationError, match="expired"):
            plane.materialize_read_model(spec, rows=[("1",)], now_ms=_NOW_MS)

        ok = plane.materialize_read_model(
            _spec(),
            rows=[("n1", "alpha")],
            now_ms=_NOW_MS,
        )
        assert ok.fence_id == "fence-1"
        assert ok.revision_bindings
        assert ok.non_authoritative is True
        assert ok.to_dict()["writer_credential_issued_to_client"] is False
        assert ok.to_dict()["authority_catalogs_attached"] is False
        assert ok.content_digest.startswith("sha256:")
    finally:
        plane.close()


# ---------------------------------------------------------------------------
# Quack serve plan uses publication gateway profile only
# ---------------------------------------------------------------------------


def test_quack_serve_plan_is_publication_gateway_without_authority_catalog() -> None:
    plane = _plane()
    try:
        plan = plane.build_quack_serve_plan()
        assert plan.profile is qs.ServerProfile.PUBLICATION_GATEWAY
        assert plan.catalog_path == ""
        assert plan.allowed_egress == ()
        assert plan.policy.external_access.enable_external_access is False
        assert plan.policy.filesystem.allow_filesystem is False
        assert plan.policy.filesystem.local_paths.allowed_paths == ()
        assert plan.policy.filesystem.allow_attach_arbitrary is False
        assert plan.policy.filesystem.allow_copy is False
        assert plan.policy.filesystem.allow_read_star is False
        assert "ducklake" not in " ".join(plan.extension_load_order)
        assert plan.os_identity_label == plane.quack_os_identity_label
        assert any(
            "enable_external_access=false" in s for s in plan.security_statements()
        )
    finally:
        plane.close()


def test_build_publication_gateway_serve_plan_rejects_authority_path() -> None:
    with pytest.raises(pub.AuthorityExposureError):
        pub.build_publication_gateway_serve_plan(
            publication_db_path="/var/lib/control.duckdb",
        )


# ---------------------------------------------------------------------------
# Schema constants stable
# ---------------------------------------------------------------------------


def test_schema_constants_stable() -> None:
    assert pub.PUBLICATION_PLANE_SCHEMA.endswith("publication-plane@1")
    assert pub.PUBLICATION_READ_MODEL_SCHEMA.endswith("publication-read-model@1")
    assert pub.PUBLICATION_MATERIALIZATION_RECEIPT_SCHEMA.endswith(
        "publication-materialization@1"
    )
    assert pub.PUBLICATION_CLIENT_CREDENTIAL_SCHEMA.endswith(
        "publication-client-credential@1"
    )
    assert pub.AUTHORITY_DATABASE_ROLES == frozenset(
        {
            "control",
            "proof",
            "graph-writer",
            "ast-writer",
            "wallet",
        }
    )


def test_plane_to_dict_is_safe() -> None:
    vault = pub.AuthorityTokenVault(clock_ms=lambda: _NOW_MS)
    vault.retain_writer_token("super-secret-writer-token-xyz")
    vault.retain_authority_token("control", "super-secret-control-token-xyz")
    plane = _plane(vault=vault)
    try:
        plane.materialize_read_model(_spec(), rows=[("a", "b")], now_ms=_NOW_MS)
        plane.register_authority_writer(_writer())
        payload = plane.to_dict()
        blob = repr(payload)
        assert "super-secret-writer-token-xyz" not in blob
        assert "super-secret-control-token-xyz" not in blob
        assert payload["schema"] == pub.PUBLICATION_PLANE_SCHEMA
        assert payload["authority_writers_unblocked_when_quack_dead"] is True
    finally:
        plane.close()


def test_row_arity_and_max_rows_enforced() -> None:
    plane = _plane()
    try:
        with pytest.raises(pub.PublicationError, match="arity"):
            plane.materialize_read_model(
                _spec(),
                rows=[("only-one-col",)],
                now_ms=_NOW_MS,
            )
        limited = pub.ReadModelSpec(
            read_model_id="rm-limited",
            table_name="public_nodes",
            columns=(
                pub.AllowlistedColumn("node_id"),
                pub.AllowlistedColumn("label"),
            ),
            revision_bindings=(_binding(),),
            fence=_fence(fence_id="fence-lim"),
            max_rows=1,
        )
        with pytest.raises(pub.PublicationError, match="max_rows"):
            plane.materialize_read_model(
                limited,
                rows=[("n1", "a"), ("n2", "b")],
                now_ms=_NOW_MS,
            )
    finally:
        plane.close()


def test_client_credential_validation_and_expiry() -> None:
    vault = pub.AuthorityTokenVault(clock_ms=lambda: _NOW_MS)
    cred = vault.mint_client_read_credential(allowed_tables=("public_nodes",), ttl_ms=10)
    assert vault.validate_client_credential(
        cred.credential_id, cred.secret, now_ms=_NOW_MS
    )
    with pytest.raises(pub.CredentialError, match="mismatch"):
        vault.validate_client_credential(cred.credential_id, "wrong-secret-value-xx")
    with pytest.raises(pub.CredentialError, match="expired"):
        vault.validate_client_credential(
            cred.credential_id, cred.secret, now_ms=cred.expires_at_ms + 1
        )
    with pytest.raises(pub.CredentialError, match="unknown"):
        vault.validate_client_credential("missing", "x" * 32)


def test_mutating_sql_denied_on_client_session() -> None:
    plane = _plane()
    try:
        plane.materialize_read_model(_spec(), rows=[("n1", "a")], now_ms=_NOW_MS)
        cred = plane.issue_client_credential()
        with plane.open_client_session(cred) as session:
            for sql in (
                "INSERT INTO public_nodes VALUES ('x', 'y')",
                "UPDATE public_nodes SET label='z'",
                "DELETE FROM public_nodes",
                "DROP TABLE public_nodes",
                "CREATE TABLE evil (id INT)",
            ):
                with pytest.raises(pub.ClientSqlRejected):
                    session.execute(sql)
    finally:
        plane.close()
