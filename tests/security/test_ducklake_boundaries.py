"""Hermetic security tests for DQK-097 DuckLake owner-broker boundaries.

Acceptance coverage:

* DuckLake exposes no native role layer and a Quack token alone cannot
  authorize any privileged lake call
* Trusted owner broker and credential issuer are distinct from workers,
  independently authorize every privileged call, and bind short-lived
  capabilities to operation, caller/process birth, endpoint owner generation,
  resource, nonce, and expiry
* Readers, writers, maintainers, and catalog owners have distinct
  endpoint/OS/storage capabilities; only independently authorized deletion
  receives separate scoped object-delete IAM
* No remote worker can open, copy, replace, or mount authority catalog files
  or companion registries
* DuckLake encryption keys and credentials are absent from logs, exports,
  receipts, and agent-visible Quack responses
* Sanitized publication Quack OS/network identity cannot reach authority
  catalog files, companion registries, object storage, or secret endpoints and
  cannot INSTALL/LOAD ducklake, quack, or httpfs
* Publication process cannot open or ATTACH the DuckLake authority catalog;
  only the distinct broker-owned DQK-104 catalog owner has a narrowly scoped
  attachment
* Publication rows bind sanitizer policy, source snapshot vector, schema, and
  digest

Importing the modules under test must not import duckdb or open network
resources.
"""

from __future__ import annotations

import builtins
import sys
from typing import Any

import pytest

from ipfs_datasets_py.ducklake import publication as pub
from ipfs_datasets_py.ducklake import security as sec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = 1_700_000_000.0
_DIGEST_A = "sha256:" + ("ab" * 32)
_DIGEST_B = "sha256:" + ("cd" * 32)
_SCHEMA_DIGEST = "sha256:" + ("11" * 32)
_VECTOR_DIGEST = "sha256:" + ("22" * 32)


def _birth(
    *,
    process_id: str = "proc-worker-1",
    boot_id: str = "boot-1",
    started_at: str = "2024-01-01T00:00:00Z",
    pid: int = 4242,
) -> sec.ProcessBirth:
    return sec.ProcessBirth(
        process_id=process_id,
        boot_id=boot_id,
        started_at=started_at,
        hostname="worker-host",
        pid=pid,
    )


def _boundary(**kwargs: Any) -> sec.DuckLakeSecurityBoundary:
    defaults = {
        "broker_id": "owner-broker-1",
        "issuer_id": "credential-issuer-1",
        "catalog_id": "catalog-a",
        "endpoint_id": "quack-endpoint-a",
        "owner_generation": 1,
        "tenant_id": "acme",
        "schema_prefix": "analytics",
        "clock": lambda: _NOW,
    }
    defaults.update(kwargs)
    return sec.DuckLakeSecurityBoundary(**defaults)


def _transport_token(
    *,
    token_id: str = "qtok-1",
    secret: str = "transport-secret-value-aaaaaaaa",
) -> sec.QuackTransportToken:
    return sec.QuackTransportToken(
        token_id=token_id,
        endpoint_id="quack-endpoint-a",
        expires_at_unix=_NOW + 300,
        _secret=secret,
    )


def _snapshot_vector(
    *,
    vector_id: str = "vec-1",
    schema_version: str = "lake-schema-1",
) -> pub.SnapshotVectorBinding:
    return pub.SnapshotVectorBinding(
        vector_id=vector_id,
        vector_digest=_VECTOR_DIGEST,
        members=(
            {
                "catalog_id": "catalog-a",
                "owner_generation": 1,
                "catalog_global_snapshot_id": 7,
                "quack_endpoint_identity": "quack-endpoint-a",
            },
        ),
        schema_version=schema_version,
        schema_digest=_SCHEMA_DIGEST,
    )


def _owner_attachment() -> pub.CatalogOwnerAttachment:
    return pub.CatalogOwnerAttachment(
        owner_process_id="dqk104-catalog-owner-1",
        catalog_id="catalog-a",
        catalog_path="/var/lib/ducklake/catalogs/catalog-a.duckdb",
        endpoint_id="quack-endpoint-a",
        owner_generation=1,
        broker_owned=True,
    )


def _plane(
    *,
    catalog_owner: pub.CatalogOwnerAttachment | None = None,
) -> pub.LakePublicationPlane:
    return pub.LakePublicationPlane(
        identity=pub.default_publication_identity(
            publication_db_path="/var/lib/publication/ducklake_public.duckdb",
            catalog_id="catalog-a",
        ),
        policy=pub.default_sanitizer_policy(),
        catalog_owner=catalog_owner if catalog_owner is not None else _owner_attachment(),
        clock=lambda: _NOW,
    )


# ---------------------------------------------------------------------------
# Import-time safety
# ---------------------------------------------------------------------------


def test_security_module_import_is_side_effect_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbidden = {"duckdb", "duckdb.experimental"}
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        root = name.split(".", 1)[0]
        if root in forbidden or name in forbidden:
            raise AssertionError(f"import of {name!r} is forbidden at module import")
        return real_import(name, globals, locals, fromlist, level)

    sys.modules.pop("ipfs_datasets_py.ducklake.security", None)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    import importlib

    mod = importlib.import_module("ipfs_datasets_py.ducklake.security")
    assert mod.DUCKLAKE_SECURITY_SCHEMA.startswith("ipfs_datasets_py/")
    assert mod.DUCKLAKE_HAS_NATIVE_ROLE_LAYER is False


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

    for name in (
        "ipfs_datasets_py.ducklake.publication",
        "ipfs_datasets_py.ducklake.security",
    ):
        sys.modules.pop(name, None)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    import importlib

    mod = importlib.import_module("ipfs_datasets_py.ducklake.publication")
    assert mod.LAKE_PUBLICATION_SCHEMA.startswith("ipfs_datasets_py/")
    assert "ducklake" in mod.FORBIDDEN_PUBLICATION_EXTENSIONS
    assert "quack" in mod.FORBIDDEN_PUBLICATION_EXTENSIONS
    assert "httpfs" in mod.FORBIDDEN_PUBLICATION_EXTENSIONS


# ---------------------------------------------------------------------------
# DuckLake has no native role layer; Quack token cannot authorize
# ---------------------------------------------------------------------------


def test_ducklake_exposes_no_native_role_layer() -> None:
    proof = sec.assert_ducklake_has_no_native_role_layer()
    assert proof["ducklake_native_role_layer"] is False
    assert proof["ducklake_authorization_layer"] is False
    assert proof["security_boundary"] == "owner_broker"
    assert sec.DUCKLAKE_HAS_NATIVE_ROLE_LAYER is False
    assert sec.QUACK_TOKEN_IS_TRANSPORT_ONLY is True

    boundary = _boundary()
    summary = boundary.proof_summary()
    assert summary["ducklake_native_role_layer"] is False
    assert summary["quack_token_is_transport_only"] is True


def test_quack_token_alone_cannot_authorize_any_privileged_call() -> None:
    token = _transport_token()
    assert token.is_transport_only is True
    assert token.authorizes_privileged_calls is False
    assert token.as_mapping()["authorizes_privileged_calls"] is False

    for op in sec.PrivilegedOperation:
        with pytest.raises(sec.AuthorizationDenied, match="cannot authorize"):
            sec.assert_quack_token_cannot_authorize(token, operation=op)
        with pytest.raises(sec.AuthorizationDenied, match="cannot authorize"):
            sec.assert_quack_token_cannot_authorize(
                token.reveal_for_trusted_transport(), operation=op
            )

    boundary = _boundary()
    with pytest.raises(sec.AuthorizationDenied, match="cannot authorize"):
        boundary.broker.deny_with_quack_token_only(
            operation=sec.PrivilegedOperation.WRITE,
            quack_token=token,
        )

    # Even with a valid transport token, broker authorization is independent;
    # the token is ignored as authority evidence.
    auth = boundary.broker.authorize(
        operation=sec.PrivilegedOperation.WRITE,
        operation_id="op-write-1",
        caller_id="worker-writer-1",
        caller_role=sec.LakeIdentityRole.WRITER,
        process_birth=_birth(),
        resource="catalog-a/data/table_a",
        quack_token=token,
    )
    assert auth["authorized"] is True
    assert auth["quack_token_sufficient"] is False
    assert auth["authorized_by"] == "trusted_owner_broker"
    assert auth["ducklake_native_role_layer"] is False


# ---------------------------------------------------------------------------
# Broker + credential issuer distinct; bind short-lived capabilities
# ---------------------------------------------------------------------------


def test_broker_and_credential_issuer_distinct_from_workers() -> None:
    boundary = _boundary()
    assert boundary.broker.broker_id != boundary.issuer.issuer_id
    summary = boundary.proof_summary()
    assert summary["broker_distinct_from_issuer"] is True

    with pytest.raises(sec.SecurityError, match="distinct"):
        sec.DuckLakeSecurityBoundary(
            broker_id="same-id",
            issuer_id="same-id",
            catalog_id="catalog-a",
            endpoint_id="ep-a",
            owner_generation=1,
        )

    with pytest.raises(sec.SecurityError, match="distinct"):
        sec.CredentialIssuer(
            issuer_id="owner-broker-1",
            broker_id="owner-broker-1",
        )

    # Broker cannot authorize itself as caller.
    with pytest.raises(sec.AuthorizationDenied, match="cannot authorize itself"):
        boundary.broker.authorize(
            operation=sec.PrivilegedOperation.READ,
            operation_id="op-self",
            caller_id=boundary.broker.broker_id,
            caller_role=sec.LakeIdentityRole.READER,
            process_birth=_birth(),
            resource="catalog-a/data",
        )


def test_broker_independently_authorizes_and_binds_capability_fields() -> None:
    boundary = _boundary()
    birth = _birth(process_id="proc-writer-9", pid=9999)
    result = boundary.authorize_and_issue(
        operation=sec.PrivilegedOperation.WRITE,
        operation_id="op-bound-1",
        caller_id="worker-writer-9",
        caller_role=sec.LakeIdentityRole.WRITER,
        process_birth=birth,
        resource="catalog-a/data/owned/file.parquet",
        capability_kind=sec.CapabilityKind.OBJECT_WRITE,
        quack_token=_transport_token(),
        ttl_seconds=45,
    )
    auth = result["authorization"]
    cap = result["capability"]

    assert auth["authorized"] is True
    assert auth["authorized_by"] == "trusted_owner_broker"
    assert auth["broker_id"] == "owner-broker-1"
    assert auth["operation"] == "write"
    assert auth["operation_id"] == "op-bound-1"
    assert auth["caller_id"] == "worker-writer-9"
    assert auth["process_birth"]["process_id"] == "proc-writer-9"
    assert auth["process_birth"]["fingerprint"] == birth.fingerprint()
    assert auth["endpoint_id"] == "quack-endpoint-a"
    assert auth["owner_generation"] == 1
    assert auth["resource"] == "catalog-a/data/owned/file.parquet"
    assert auth["nonce"]
    assert auth["expires_at_unix"] > _NOW
    assert "tenant_schema" in auth
    assert auth["tenant_schema"]["tenant_id"] == "acme"
    assert auth["encryption_policy"]["required"] is True

    assert cap["kind"] == "object_write"
    assert cap["operation"] == "write"
    assert cap["operation_id"] == "op-bound-1"
    assert cap["caller_id"] == "worker-writer-9"
    assert cap["process_birth"]["fingerprint"] == birth.fingerprint()
    assert cap["endpoint_id"] == "quack-endpoint-a"
    assert cap["owner_generation"] == 1
    assert cap["resource"] == "catalog-a/data/owned/file.parquet"
    assert cap["nonce"]
    assert cap["expires_at_unix"] == pytest.approx(_NOW + 45)
    assert cap["issuer_id"] == "credential-issuer-1"
    assert cap["authorization_id"] == auth["authorization_id"]
    assert cap["secret"] == sec.REDACTION_MARKER
    assert "object_delete_iam" not in result

    # Issuer refuses without broker authorization.
    with pytest.raises(sec.AuthorizationDenied, match="without broker"):
        boundary.issuer.issue_capability(
            authorization={"authorized": False},
            kind=sec.CapabilityKind.QUACK_TRANSPORT,
            process_birth=birth,
        )


def test_owner_generation_mismatch_denies() -> None:
    boundary = _boundary(owner_generation=3)
    with pytest.raises(sec.AuthorizationDenied, match="generation mismatch"):
        boundary.broker.authorize(
            operation=sec.PrivilegedOperation.READ,
            operation_id="op-gen",
            caller_id="worker-1",
            caller_role=sec.LakeIdentityRole.READER,
            process_birth=_birth(),
            resource="catalog-a/data",
            owner_generation=2,
        )


def test_process_birth_mismatch_on_capability_issue() -> None:
    boundary = _boundary()
    birth_a = _birth(process_id="proc-a")
    birth_b = _birth(process_id="proc-b")
    auth = boundary.broker.authorize(
        operation=sec.PrivilegedOperation.READ,
        operation_id="op-pb",
        caller_id="worker-1",
        caller_role=sec.LakeIdentityRole.READER,
        process_birth=birth_a,
        resource="catalog-a/data",
    )
    with pytest.raises(sec.CapabilityError, match="process_birth mismatch"):
        boundary.issuer.issue_capability(
            authorization=auth,
            kind=sec.CapabilityKind.QUACK_TRANSPORT,
            process_birth=birth_b,
        )


# ---------------------------------------------------------------------------
# Distinct role capabilities + object-delete IAM
# ---------------------------------------------------------------------------


def test_roles_have_distinct_endpoint_os_storage_capabilities() -> None:
    identities = sec.default_identity_capabilities(catalog_id="catalog-a")
    reader = identities[sec.LakeIdentityRole.READER]
    writer = identities[sec.LakeIdentityRole.WRITER]
    maintainer = identities[sec.LakeIdentityRole.MAINTAINER]
    owner = identities[sec.LakeIdentityRole.CATALOG_OWNER]

    assert reader.os_identity != writer.os_identity
    assert writer.os_identity != maintainer.os_identity
    assert maintainer.os_identity != owner.os_identity
    assert reader.network_identity != owner.network_identity

    assert reader.object_read is True
    assert reader.object_write is False
    assert reader.object_delete is False
    assert reader.open_catalog_file is False
    assert reader.may_request_object_delete_iam is False

    assert writer.object_write is True
    assert writer.object_delete is False
    assert writer.open_catalog_file is False
    assert writer.may_request_object_delete_iam is False

    assert maintainer.object_write is True
    assert maintainer.object_delete is False
    assert maintainer.open_catalog_file is False
    assert maintainer.may_request_object_delete_iam is True

    assert owner.is_catalog_owner_process is True
    assert owner.open_catalog_file is True
    assert owner.open_companion_registry is True
    assert owner.mount_authority_files is False
    assert owner.object_delete is False
    assert owner.may_request_object_delete_iam is True

    # Invariant violations fail closed.
    with pytest.raises(sec.SecurityError, match="reader"):
        sec.IdentityEndpointCapabilities(
            role=sec.LakeIdentityRole.READER,
            os_identity="bad_reader",
            network_identity="net_bad",
            endpoint_access=True,
            object_read=True,
            object_write=True,
        )


def test_only_authorized_deletion_receives_object_delete_iam() -> None:
    boundary = _boundary()
    birth = _birth(process_id="proc-maint-1")

    # Reader cannot delete / obtain object-delete IAM.
    with pytest.raises(sec.AuthorizationDenied, match="delete requires"):
        boundary.broker.authorize(
            operation=sec.PrivilegedOperation.DELETE,
            operation_id="op-del-reader",
            caller_id="worker-reader-1",
            caller_role=sec.LakeIdentityRole.READER,
            process_birth=birth,
            resource="catalog-a/data/file.parquet",
            approve_object_delete_iam=True,
        )

    # Writer cannot delete.
    with pytest.raises(sec.AuthorizationDenied, match="delete requires"):
        boundary.broker.authorize(
            operation=sec.PrivilegedOperation.DELETE,
            operation_id="op-del-writer",
            caller_id="worker-writer-1",
            caller_role=sec.LakeIdentityRole.WRITER,
            process_birth=birth,
            resource="catalog-a/data/file.parquet",
            approve_object_delete_iam=True,
        )

    # Maintainer without explicit IAM approval is denied.
    with pytest.raises(sec.AuthorizationDenied, match="object-delete IAM approval"):
        boundary.broker.authorize(
            operation=sec.PrivilegedOperation.DELETE,
            operation_id="op-del-no-iam",
            caller_id="worker-maint-1",
            caller_role=sec.LakeIdentityRole.MAINTAINER,
            process_birth=birth,
            resource="catalog-a/data/file.parquet",
            approve_object_delete_iam=False,
        )

    # Independently authorized deletion issues separate scoped IAM.
    result = boundary.authorize_and_issue(
        operation=sec.PrivilegedOperation.DELETE,
        operation_id="op-del-ok",
        caller_id="worker-maint-1",
        caller_role=sec.LakeIdentityRole.MAINTAINER,
        process_birth=birth,
        resource="catalog-a/data/owned/orphan.parquet",
        capability_kind=sec.CapabilityKind.OBJECT_DELETE_IAM,
        approve_object_delete_iam=True,
        delete_scope_prefix="catalog-a/data/owned/",
    )
    assert result["authorization"]["object_delete_iam_approved"] is True
    iam = result["object_delete_iam"]
    assert iam["ambient"] is False
    assert iam["scope_prefix"] == "catalog-a/data/owned/"
    assert iam["operation_id"] == "op-del-ok"
    assert iam["caller_id"] == "worker-maint-1"
    assert iam["owner_generation"] == 1
    assert iam["nonce"]
    assert iam["secret"] == sec.REDACTION_MARKER
    assert iam["issuer_id"] == "credential-issuer-1"


def test_capability_is_one_use() -> None:
    boundary = _boundary()
    birth = _birth()
    auth = boundary.broker.authorize(
        operation=sec.PrivilegedOperation.READ,
        operation_id="op-once",
        caller_id="worker-1",
        caller_role=sec.LakeIdentityRole.READER,
        process_birth=birth,
        resource="catalog-a/data",
    )
    cap = boundary.issuer.issue_capability(
        authorization=auth,
        kind=sec.CapabilityKind.QUACK_TRANSPORT,
        process_birth=birth,
    )
    used = cap.mark_used()
    assert used.used is True
    with pytest.raises(sec.CapabilityError, match="already used"):
        used.mark_used()


# ---------------------------------------------------------------------------
# Remote workers cannot open/copy/replace/mount authority files
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action",
    [
        "open",
        "copy",
        "replace",
        "mount",
        "network_mount",
        "nfs_mount",
        "smb_mount",
        "attach_path",
        "overwrite",
    ],
)
def test_remote_worker_cannot_touch_authority_catalog_or_registry(
    action: str,
) -> None:
    boundary = _boundary()
    with pytest.raises(sec.RemoteAccessDenied):
        boundary.broker.assert_remote_worker_denied(
            action, target="authority_catalog"
        )
    with pytest.raises(sec.RemoteAccessDenied):
        sec.assert_remote_authority_action_denied(
            action, target="companion_registry"
        )


def test_reader_writer_cannot_attach_authority_catalog() -> None:
    boundary = _boundary()
    for role in (sec.LakeIdentityRole.READER, sec.LakeIdentityRole.WRITER):
        with pytest.raises(sec.AuthorizationDenied, match="catalog owner"):
            boundary.broker.authorize(
                operation=sec.PrivilegedOperation.ATTACH,
                operation_id=f"op-attach-{role.value}",
                caller_id=f"worker-{role.value}",
                caller_role=role,
                process_birth=_birth(),
                resource="/var/lib/ducklake/catalogs/catalog-a.duckdb",
            )


# ---------------------------------------------------------------------------
# Credentials / encryption keys absent from logs, exports, receipts, agents
# ---------------------------------------------------------------------------


def test_encryption_keys_and_credentials_absent_from_surfaces() -> None:
    boundary = _boundary()
    birth = _birth()
    result = boundary.authorize_and_issue(
        operation=sec.PrivilegedOperation.WRITE,
        operation_id="op-scrub",
        caller_id="worker-1",
        caller_role=sec.LakeIdentityRole.WRITER,
        process_birth=birth,
        resource="catalog-a/data",
        capability_kind=sec.CapabilityKind.OBJECT_WRITE,
    )

    leaky = {
        "authorization": dict(result["authorization"]),
        "capability": dict(result["capability"]),
        "encryption_key": "0123456789abcdef0123456789abcdef",
        "quack_token": "super-secret-token-material-xyz",
        "nested": {
            "private_key": "BEGIN PRIVATE KEY\nabc\n",
            "file_key": "aa" * 32,
            "safe_id": "dataset-1",
            "content_digest": _DIGEST_A,
        },
    }
    for surface_name, redactor in (
        ("log", sec.redact_for_log),
        ("export", sec.redact_for_export),
        ("receipt", sec.redact_for_receipt),
        ("agent_quack", sec.redact_for_agent_quack_response),
    ):
        scrubbed = redactor(leaky)
        blob = repr(scrubbed)
        assert "super-secret-token-material" not in blob
        assert "BEGIN PRIVATE KEY" not in blob
        assert scrubbed["encryption_key"] == sec.REDACTION_MARKER
        assert scrubbed["quack_token"] == sec.REDACTION_MARKER
        assert scrubbed["nested"]["private_key"] == sec.REDACTION_MARKER
        assert scrubbed["nested"]["file_key"] == sec.REDACTION_MARKER
        assert scrubbed["nested"]["safe_id"] == "dataset-1"
        assert scrubbed["nested"]["content_digest"] == _DIGEST_A
        assert scrubbed["capability"]["secret"] == sec.REDACTION_MARKER
        assert surface_name  # silence unused in some linters

    # Capability / token repr never leaks secrets.
    token = _transport_token(secret="must-not-appear-in-repr-1234567890")
    assert "must-not-appear" not in repr(token)
    assert "must-not-appear" not in str(token)

    plane = _plane()
    try:
        receipt = plane.copy_publish(
            table_name="public_datasets",
            rows=[
                {
                    "dataset_id": "ds-1",
                    "catalog_id": "catalog-a",
                    "row_count": 10,
                    "snapshot_id": 7,
                    "content_digest": _DIGEST_A,
                    "encryption_key": "should-be-stripped-or-redacted",
                }
            ],
            snapshot_vector=_snapshot_vector(),
        )
        agent_view = plane.agent_visible_projection()
        agent_blob = repr(agent_view)
        assert "should-be-stripped" not in agent_blob
        assert "must-not-appear" not in agent_blob
        assert receipt.as_mapping()["authority_catalog_attached"] is False
        # Sensitive column names never land in published payload.
        rows = agent_view["tables"]["public_datasets"]
        assert rows
        assert "encryption_key" not in rows[0]["payload"]
    finally:
        plane.close()


def test_audit_events_bind_endpoint_and_owner_generation() -> None:
    boundary = _boundary(owner_generation=5)
    boundary.broker.authorize(
        operation=sec.PrivilegedOperation.SNAPSHOT,
        operation_id="op-snap-1",
        caller_id="worker-reader-1",
        caller_role=sec.LakeIdentityRole.READER,
        process_birth=_birth(),
        resource="catalog-a/snapshots",
    )
    events = boundary.broker.audit_events()
    assert events
    event = events[-1]
    assert event.endpoint_id == "quack-endpoint-a"
    assert event.owner_generation == 5
    assert event.operation_id == "op-snap-1"
    assert event.decision == "allow"
    mapping = event.as_mapping()
    assert mapping["endpoint_id"] == "quack-endpoint-a"
    assert mapping["owner_generation"] == 5


def test_tenant_schema_prefixes_and_encrypted_parquet_policy() -> None:
    prefix = sec.TenantSchemaPrefix(tenant_id="acme", schema_prefix="analytics")
    assert prefix.qualified_schema() == "acme__analytics"
    assert prefix.qualify_table("metrics") == "acme__analytics.metrics"
    with pytest.raises(sec.SecurityError):
        sec.TenantSchemaPrefix(tenant_id="Acme!", schema_prefix="bad")

    policy = sec.default_encrypted_parquet_policy(key_ref_id="enc-ref-1")
    assert policy.required is True
    assert policy.algorithm == "aes-256-gcm"
    assert policy.as_mapping()["key_material_embedded"] is False
    with pytest.raises(sec.SecurityError, match="transit TLS"):
        sec.EncryptedParquetPolicy(required=True, transit_tls_required=False)


# ---------------------------------------------------------------------------
# Publication plane isolation
# ---------------------------------------------------------------------------


def test_publication_identity_cannot_reach_authority_surfaces() -> None:
    plane = _plane()
    try:
        identity = plane.identity
        assert identity.isolated_from_authority is True
        assert identity.may_open_authority_catalog is False
        assert identity.may_attach_authority_catalog is False
        assert identity.may_reach_companion_registry is False
        assert identity.may_reach_object_storage is False
        assert identity.may_reach_secret_endpoints is False

        for target in (
            "authority_catalog",
            "companion_registry",
            "object_storage",
            "secret_endpoint",
            "s3://bucket/key",
            "/var/lib/ducklake/catalogs/catalog-a.duckdb",
            "/var/lib/ducklake/registries/companion.duckdb",
            "vault_endpoint",
        ):
            with pytest.raises(pub.PublicationReachabilityError):
                plane.attempt_reach(target)
    finally:
        plane.close()


def test_publication_cannot_install_or_load_ducklake_quack_httpfs() -> None:
    plane = _plane()
    try:
        for ext in ("ducklake", "quack", "httpfs", "ducklake@1.5.5+core"):
            with pytest.raises(pub.ExtensionDenied):
                plane.attempt_install_extension(ext)
            with pytest.raises(pub.ExtensionDenied):
                plane.attempt_load_extension(ext)

        for sql in (
            "INSTALL ducklake",
            "LOAD quack",
            "LOAD httpfs",
            "INSTALL httpfs; LOAD httpfs",
        ):
            with pytest.raises((pub.ExtensionDenied, pub.PublicationError)):
                plane.execute_client_sql(sql)
    finally:
        plane.close()


def test_publication_cannot_open_or_attach_authority_catalog() -> None:
    plane = _plane()
    try:
        with pytest.raises(pub.AuthorityAttachDenied, match="cannot open or ATTACH"):
            plane.attempt_attach_authority(
                "/var/lib/ducklake/catalogs/catalog-a.duckdb"
            )
        with pytest.raises(pub.AuthorityAttachDenied):
            plane.execute_client_sql(
                "ATTACH 'ducklake:/var/lib/ducklake/catalogs/catalog-a.duckdb' "
                "AS lake"
            )
        assert plane.authority_catalog_attached is False

        # Only DQK-104 catalog owner has narrowly scoped attachment.
        owner = plane.catalog_owner
        assert owner is not None
        assert owner.broker_owned is True
        assert owner.as_mapping()["dqk104_catalog_owner"] is True
        assert owner.as_mapping()["CREATE_IF_NOT_EXISTS"] is False
        assert owner.as_mapping()["OVERRIDE_DATA_PATH"] is False
        assert owner.as_mapping()["AUTOMATIC_MIGRATION"] is False
        assert owner.owner_process_id != plane.identity.os_identity
    finally:
        plane.close()


def test_publication_rows_bind_policy_snapshot_schema_and_digest() -> None:
    plane = _plane()
    try:
        vector = _snapshot_vector()
        receipt = plane.copy_publish(
            table_name="public_aggregates",
            rows=[
                {
                    "dataset_id": "ds-agg-1",
                    "catalog_id": "catalog-a",
                    "row_count": 42,
                    "snapshot_id": 7,
                    "content_digest": _DIGEST_B,
                }
            ],
            snapshot_vector=vector,
            publication_id="pub-bind-1",
        )
        assert receipt.sanitizer_policy_id == plane.policy.policy_id
        assert receipt.snapshot_vector_id == vector.vector_id
        assert receipt.snapshot_vector_digest == vector.vector_digest
        assert receipt.schema_version == vector.schema_version
        assert receipt.schema_digest == vector.schema_digest
        assert receipt.content_digest.startswith("sha256:")
        assert receipt.authority_catalog_attached is False
        assert receipt.extensions_loaded == ()

        rows = plane.agent_visible_projection()["tables"]["public_aggregates"]
        assert len(rows) == 1
        row = rows[0]
        assert row["sanitizer_policy_id"] == plane.policy.policy_id
        assert row["snapshot_vector"]["vector_id"] == vector.vector_id
        assert row["snapshot_vector"]["vector_digest"] == vector.vector_digest
        assert row["schema_version"] == vector.schema_version
        assert row["schema_digest"] == vector.schema_digest
        assert row["content_digest"].startswith("sha256:")
        assert row["authority_catalog_attached"] is False
        assert row["payload"]["dataset_id"] == "ds-agg-1"
    finally:
        plane.close()


def test_publication_rejects_non_allowlisted_table_and_empty_payload() -> None:
    plane = _plane()
    try:
        vector = _snapshot_vector()
        with pytest.raises(pub.SanitizerPolicyError, match="not allowlisted"):
            plane.copy_publish(
                table_name="secret_internal",
                rows=[{"dataset_id": "x"}],
                snapshot_vector=vector,
            )
        with pytest.raises(pub.SanitizerPolicyError, match="no allowlisted"):
            plane.copy_publish(
                table_name="public_datasets",
                rows=[{"not_a_column": "x"}],
                snapshot_vector=vector,
            )
    finally:
        plane.close()


def test_publication_identity_must_differ_from_catalog_owner() -> None:
    with pytest.raises(pub.PublicationIdentityError, match="distinct"):
        pub.PublicationIdentity(
            os_identity="pub-os",
            network_identity="pub-net",
            publication_db_path="/var/lib/publication/public.duckdb",
            distinct_from_catalog_owner=False,
        )

    owner = _owner_attachment()
    # Force same OS identity as owner — plane construction fails.
    identity = pub.PublicationIdentity(
        os_identity=owner.owner_process_id,
        network_identity="net_publication",
        publication_db_path="/var/lib/publication/public.duckdb",
    )
    with pytest.raises(pub.PublicationIdentityError, match="differ"):
        pub.LakePublicationPlane(
            identity=identity,
            policy=pub.default_sanitizer_policy(),
            catalog_owner=owner,
        )


def test_catalog_owner_attachment_requires_safe_flags() -> None:
    with pytest.raises(pub.PublicationError, match="broker-owned"):
        pub.CatalogOwnerAttachment(
            owner_process_id="owner-1",
            catalog_id="catalog-a",
            catalog_path="/var/lib/ducklake/catalogs/catalog-a.duckdb",
            endpoint_id="ep-a",
            owner_generation=1,
            broker_owned=False,
        )
    with pytest.raises(pub.PublicationError, match="CREATE_IF_NOT_EXISTS"):
        pub.CatalogOwnerAttachment(
            owner_process_id="owner-1",
            catalog_id="catalog-a",
            catalog_path="/var/lib/ducklake/catalogs/catalog-a.duckdb",
            endpoint_id="ep-a",
            owner_generation=1,
            create_if_not_exists=True,
        )


def test_publication_row_requires_matching_schema_binding() -> None:
    vector = _snapshot_vector(schema_version="schema-v1")
    with pytest.raises(pub.PublicationError, match="schema_version"):
        pub.PublicationRow(
            row_id="row-1",
            table_name="public_datasets",
            payload={"dataset_id": "ds-1"},
            sanitizer_policy_id="sanitizer-default",
            snapshot_vector=vector,
            schema_version="schema-v2",
            schema_digest=_SCHEMA_DIGEST,
            content_digest="",
        )
    with pytest.raises(pub.PublicationError, match="schema_digest"):
        pub.PublicationRow(
            row_id="row-2",
            table_name="public_datasets",
            payload={"dataset_id": "ds-1"},
            sanitizer_policy_id="sanitizer-default",
            snapshot_vector=vector,
            schema_version="schema-v1",
            schema_digest=_DIGEST_A,
            content_digest="",
        )


def test_maintainer_cannot_write_without_role_check_for_reader() -> None:
    boundary = _boundary()
    with pytest.raises(sec.AuthorizationDenied, match="cannot write"):
        boundary.broker.authorize(
            operation=sec.PrivilegedOperation.WRITE,
            operation_id="op-r-write",
            caller_id="worker-reader-1",
            caller_role=sec.LakeIdentityRole.READER,
            process_birth=_birth(),
            resource="catalog-a/data",
        )
    with pytest.raises(sec.AuthorizationDenied, match="maintenance requires"):
        boundary.broker.authorize(
            operation=sec.PrivilegedOperation.COMPACT,
            operation_id="op-r-compact",
            caller_id="worker-writer-1",
            caller_role=sec.LakeIdentityRole.WRITER,
            process_birth=_birth(),
            resource="catalog-a/data",
        )
