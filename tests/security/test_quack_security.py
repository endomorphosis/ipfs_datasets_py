"""Hermetic security tests for DQK-049 Quack threat model and guarded launcher.

Acceptance coverage:

* Default authentication and authorization are never permissive for agent traffic
* Fresh catalog-owner connections require a one-use operation capability through
  a non-default authentication callback or authenticating proxy
* Publication and catalog-owner profiles have distinct external-access, extension,
  local-path, filesystem, and egress policies
* A catalog owner can reach only its exact local catalog path and selected object
  endpoint/TLS proxy; a publication gateway reaches neither
* Remote plaintext exposure is rejected
* Tokens and full SQL text are handled as sensitive

Importing the module under test must not import duckdb or open network resources.
"""

from __future__ import annotations

import builtins
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.duckdb_control import quack_security as qs


# ---------------------------------------------------------------------------
# Import-time safety
# ---------------------------------------------------------------------------


def test_quack_security_module_import_is_side_effect_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbidden = {"duckdb", "duckdb.experimental"}
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        root = name.split(".", 1)[0]
        if root in forbidden or name in forbidden:
            raise AssertionError(f"import of {name!r} is forbidden at module import")
        return real_import(name, globals, locals, fromlist, level)

    sys.modules.pop("ipfs_datasets_py.duckdb_control.quack_security", None)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    import importlib

    mod = importlib.import_module("ipfs_datasets_py.duckdb_control.quack_security")
    assert mod.QUACK_SECURITY_SCHEMA.startswith("ipfs_datasets_py/")
    assert mod.QUACK_THREAT_MODEL.threats


# ---------------------------------------------------------------------------
# Threat model
# ---------------------------------------------------------------------------


def test_threat_model_covers_required_controls() -> None:
    model = qs.QUACK_THREAT_MODEL
    summary = qs.threat_model_summary()
    assert summary["schema"] == qs.QUACK_SECURITY_SCHEMA
    assert model.assets
    assert model.trust_boundaries
    threat_ids = {t.threat_id for t in model.threats}
    assert qs.ThreatId.T1_PERMISSIVE_DEFAULT_AUTH in threat_ids
    assert qs.ThreatId.T2_REUSABLE_TOKEN_AS_AUTHORITY in threat_ids
    assert qs.ThreatId.T5_REMOTE_PLAINTEXT in threat_ids
    assert qs.ThreatId.T6_TOKEN_SQL_LOG_LEAK in threat_ids
    # Every threat has at least one control.
    for entry in model.threats:
        assert entry.controls
        assert entry.title
        assert entry.description


# ---------------------------------------------------------------------------
# Default auth/authz never permissive for agents
# ---------------------------------------------------------------------------


def test_default_authentication_and_authorization_never_permissive() -> None:
    assert qs.default_auth_is_permissive_for_agents() is False
    assert qs.default_authz_is_permissive_for_agents() is False

    auth = qs.AuthenticationPolicy()
    authz = qs.AuthorizationPolicy()
    assert auth.mode is qs.AuthenticationMode.DENY
    assert authz.mode is qs.AuthorizationMode.DENY_ALL
    assert auth.is_permissive_for_agents() is False
    assert authz.is_permissive_for_agents() is False

    with pytest.raises(qs.QuackSecurityError, match="never be permissive"):
        qs.AuthenticationPolicy(allow_agent_default_auth=True)
    with pytest.raises(qs.QuackSecurityError, match="never be permissive"):
        qs.AuthorizationPolicy(allow_agent_default_authz=True)
    with pytest.raises(qs.QuackSecurityError, match="reusable server token"):
        qs.AuthenticationPolicy(
            mode=qs.AuthenticationMode.ONE_USE_CAPABILITY_CALLBACK,
            callback_name=qs.NON_DEFAULT_AUTH_CALLBACK_NAME,
            reusable_token_is_authority=True,
        )
    with pytest.raises(qs.QuackSecurityError, match="prefix/regex"):
        qs.AuthorizationPolicy(
            mode=qs.AuthorizationMode.EXACT_FULL_SQL,
            callback_name=qs.NON_DEFAULT_AUTHZ_CALLBACK_NAME,
            allow_prefix_match=True,
        )


# ---------------------------------------------------------------------------
# Profile construction and distinctness
# ---------------------------------------------------------------------------


_CATALOG_PATH = "/var/lib/ducklake/shard-a/catalog.duckdb"
_OBJECT = qs.EgressEndpoint(
    host="objects.example.internal",
    port=443,
    scheme="https",
    role="object_endpoint",
)
_TLS_PROXY = qs.EgressEndpoint(
    host="tls-proxy.example.internal",
    port=8443,
    scheme="tls",
    role="tls_proxy",
)


def _publication() -> qs.ProfileSecurityPolicy:
    return qs.publication_gateway_policy()


def _owner(
    *,
    auth_mode: qs.AuthenticationMode = qs.AuthenticationMode.ONE_USE_CAPABILITY_CALLBACK,
) -> qs.ProfileSecurityPolicy:
    return qs.catalog_owner_policy(
        catalog_path=_CATALOG_PATH,
        object_endpoint=_OBJECT,
        tls_proxy=_TLS_PROXY,
        authentication_mode=auth_mode,
    )


def test_publication_and_catalog_owner_policies_are_distinct() -> None:
    pub = _publication()
    owner = _owner()
    qs.assert_profiles_distinct(pub, owner)

    assert pub.external_access.to_dict() != owner.external_access.to_dict() or (
        pub.extensions.to_dict() != owner.extensions.to_dict()
    )
    # Explicit dimension checks required by acceptance.
    assert pub.external_access.enable_external_access is False
    assert owner.external_access.enable_external_access is True
    assert pub.external_access.to_dict() != owner.external_access.to_dict()
    assert pub.extensions.pinned_builds != owner.extensions.pinned_builds
    assert pub.filesystem.local_paths.allowed_paths != owner.filesystem.local_paths.allowed_paths
    assert pub.filesystem.allow_filesystem != owner.filesystem.allow_filesystem
    assert pub.egress.allowed_endpoints != owner.egress.allowed_endpoints
    assert "ducklake" not in " ".join(pub.extensions.pinned_builds)
    assert any("ducklake" in b for b in owner.extensions.pinned_builds)


def test_catalog_owner_reaches_only_exact_catalog_and_selected_egress() -> None:
    owner = _owner()
    assert owner.filesystem.allows_path(_CATALOG_PATH) is True
    assert owner.filesystem.allows_path(_CATALOG_PATH + ".bak") is False
    assert owner.filesystem.allows_path("/etc/passwd") is False
    assert owner.filesystem.allows_path("/var/lib/ducklake/shard-a/other.duckdb") is False

    assert owner.egress.allows(_OBJECT.host, _OBJECT.port) is True
    assert owner.egress.allows(_TLS_PROXY.host, _TLS_PROXY.port) is True
    assert owner.egress.allows("evil.example", 443) is False
    assert owner.egress.allows(_OBJECT.host, 80) is False
    assert owner.egress.allows_url("https://objects.example.internal/bucket/key") is True
    assert owner.egress.allows_url("https://evil.example/bucket") is False


def test_publication_gateway_reaches_neither_catalog_nor_object_endpoint() -> None:
    pub = _publication()
    assert pub.filesystem.allow_filesystem is False
    assert pub.filesystem.local_paths.allowed_paths == ()
    assert pub.filesystem.allows_path(_CATALOG_PATH) is False
    assert pub.egress.allowed_endpoints == ()
    assert pub.egress.allows(_OBJECT.host, _OBJECT.port) is False
    assert pub.egress.allows(_TLS_PROXY.host, _TLS_PROXY.port) is False
    assert pub.external_access.enable_external_access is False

    owner = _owner()
    # Distinctness helper must accept a valid publication/owner pair.
    qs.assert_profiles_distinct(pub, owner)


def test_publication_rejects_catalog_path_and_object_extension_pins() -> None:
    with pytest.raises(qs.ProfileMismatchError, match="local catalog"):
        qs.ProfileSecurityPolicy(
            profile=qs.ServerProfile.PUBLICATION_GATEWAY,
            external_access=qs.ExternalAccessPolicy(),
            extensions=qs.ExtensionPolicy(pinned_builds=qs.PINNED_PUBLICATION_EXTENSIONS),
            filesystem=qs.FilesystemPolicy(
                allow_filesystem=True,
                local_paths=qs.LocalPathPolicy(allowed_paths=(_CATALOG_PATH,)),
            ),
            egress=qs.EgressPolicy(),
            network=qs.NetworkExposurePolicy(),
            authentication=qs.AuthenticationPolicy(
                mode=qs.AuthenticationMode.ONE_USE_CAPABILITY_CALLBACK,
                callback_name=qs.NON_DEFAULT_AUTH_CALLBACK_NAME,
            ),
            authorization=qs.AuthorizationPolicy(
                mode=qs.AuthorizationMode.EXACT_FULL_SQL,
                callback_name=qs.NON_DEFAULT_AUTHZ_CALLBACK_NAME,
            ),
            os_identity=qs.OSIdentityPolicy(identity_label="pub"),
            audit=qs.AuditPolicy(),
            sensitive=qs.SensitiveDataPolicy(),
        )


def test_catalog_owner_requires_one_use_auth_and_pinned_extensions() -> None:
    with pytest.raises(qs.QuackSecurityError, match="one-use"):
        qs.catalog_owner_policy(
            catalog_path=_CATALOG_PATH,
            object_endpoint=_OBJECT,
            authentication_mode=qs.AuthenticationMode.DENY,  # type: ignore[arg-type]
        )
    # AUTHENTICATING_PROXY is explicitly allowed.
    proxy_owner = _owner(auth_mode=qs.AuthenticationMode.AUTHENTICATING_PROXY)
    assert (
        proxy_owner.authentication.mode
        is qs.AuthenticationMode.AUTHENTICATING_PROXY
    )
    assert set(qs.PINNED_CATALOG_OWNER_EXTENSIONS).issubset(
        set(proxy_owner.extensions.pinned_builds)
    )


# ---------------------------------------------------------------------------
# One-use capability + non-default authentication
# ---------------------------------------------------------------------------


def test_fresh_catalog_owner_connection_requires_one_use_capability() -> None:
    launcher = qs.GuardedServerLauncher()
    config = qs.build_guarded_config(
        qs.ServerProfile.CATALOG_OWNER,
        catalog_path=_CATALOG_PATH,
        object_host=_OBJECT.host,
        object_port=_OBJECT.port,
        tls_proxy_host=_TLS_PROXY.host,
        tls_proxy_port=_TLS_PROXY.port,
    )
    plan = launcher.plan(config)
    assert plan.authentication_callback == qs.NON_DEFAULT_AUTH_CALLBACK_NAME
    assert plan.authentication_callback.lower() not in qs.DEFAULT_PERMISSIVE_AUTH_HOOKS
    assert plan.authorization_callback == qs.NON_DEFAULT_AUTHZ_CALLBACK_NAME

    auth, authz = launcher.install_callbacks(plan)
    assert auth.is_default is False
    assert authz.is_default is False

    sql = "SELECT snapshot_id FROM lake.snapshots WHERE snapshot_id = ?"
    cap = launcher.mint_and_register(
        operation_id="op-catalog-1",
        profile=qs.ServerProfile.CATALOG_OWNER,
        canonical_sql=sql,
        ttl_ms=60_000,
        now_ms=1_000_000,
    )
    # Secret never appears in redacted/log views.
    redacted = cap.redacted_dict()
    assert redacted["secret"] == qs.REDACTION_MARKER
    assert cap.secret not in repr(cap)
    assert cap.secret not in str(cap)
    assert sql not in repr(cap) or qs.REDACTION_MARKER in repr(cap)

    session = launcher.authenticate_fresh_connection(
        qs.ServerProfile.CATALOG_OWNER,
        capability_secret=cap.secret,
        now_ms=1_000_100,
    )
    assert session.operation_id == "op-catalog-1"
    assert session.session_id
    assert session.canonical_sql == sql
    assert cap.secret not in repr(session)

    # Reuse fails closed.
    with pytest.raises(qs.AuthenticationError, match="unknown|consumed"):
        launcher.authenticate_fresh_connection(
            qs.ServerProfile.CATALOG_OWNER,
            capability_secret=cap.secret,
            now_ms=1_000_200,
        )

    # Exact SQL authorized.
    assert launcher.authorize_sql(
        qs.ServerProfile.CATALOG_OWNER,
        session_id=session.session_id,
        sql=sql,
    ) is True

    # Prefix / different SQL denied.
    with pytest.raises(qs.AuthorizationError):
        launcher.authorize_sql(
            qs.ServerProfile.CATALOG_OWNER,
            session_id=session.session_id,
            sql="SELECT snapshot_id FROM lake.snapshots",
        )
    with pytest.raises(qs.AuthorizationError):
        launcher.authorize_sql(
            qs.ServerProfile.CATALOG_OWNER,
            session_id=session.session_id,
            sql=sql + " OR 1=1",
        )

    # Missing capability fails closed.
    with pytest.raises(qs.AuthenticationError):
        launcher.authenticate_fresh_connection(
            qs.ServerProfile.CATALOG_OWNER,
            capability_secret="not-a-real-capability-secret",
            now_ms=1_000_300,
        )


def test_expired_capability_is_rejected() -> None:
    store = qs.OperationCapabilityStore()
    cap = qs.mint_operation_capability(
        operation_id="op-expired",
        profile=qs.ServerProfile.CATALOG_OWNER,
        canonical_sql="SELECT 1",
        ttl_ms=10,
        now_ms=1000,
    )
    store.insert(cap)
    auth_policy = qs.AuthenticationPolicy(
        mode=qs.AuthenticationMode.ONE_USE_CAPABILITY_CALLBACK,
        callback_name=qs.NON_DEFAULT_AUTH_CALLBACK_NAME,
    )
    auth = qs.AuthenticationCallback(
        store,
        profile=qs.ServerProfile.CATALOG_OWNER,
        policy=auth_policy,
    )
    with pytest.raises(qs.AuthenticationError, match="expired"):
        auth.authenticate(capability_secret=cap.secret, now_ms=1011)


def test_authenticating_proxy_mode_also_consumes_one_use_capability() -> None:
    owner = _owner(auth_mode=qs.AuthenticationMode.AUTHENTICATING_PROXY)
    assert owner.authentication.mode is qs.AuthenticationMode.AUTHENTICATING_PROXY
    launcher = qs.GuardedServerLauncher()
    plan = launcher.plan(
        qs.GuardedServerConfig(
            policy=owner,
            catalog_path=_CATALOG_PATH,
            object_endpoint=_OBJECT,
            tls_proxy=_TLS_PROXY,
        )
    )
    launcher.install_callbacks(plan)
    cap = launcher.mint_and_register(
        operation_id="op-proxy",
        profile=qs.ServerProfile.CATALOG_OWNER,
        canonical_sql="SELECT 42",
    )
    session = launcher.authenticate_fresh_connection(
        qs.ServerProfile.CATALOG_OWNER,
        capability_secret=cap.secret,
    )
    assert session.operation_id == "op-proxy"


# ---------------------------------------------------------------------------
# Remote plaintext exposure
# ---------------------------------------------------------------------------


def test_remote_plaintext_exposure_is_rejected() -> None:
    qs.reject_remote_plaintext(bind_host="127.0.0.1")
    qs.reject_remote_plaintext(bind_host="localhost")
    qs.reject_remote_plaintext(bind_host="::1")

    with pytest.raises(qs.ExposureError, match="plaintext"):
        qs.reject_remote_plaintext(bind_host="203.0.113.10")
    with pytest.raises(qs.ExposureError):
        qs.reject_remote_plaintext(bind_host="0.0.0.0")
    with pytest.raises(qs.ExposureError):
        qs.reject_remote_plaintext(
            bind_host="203.0.113.10",
            use_tls=True,
        )
    with pytest.raises(qs.ExposureError):
        qs.reject_remote_plaintext(
            bind_host="203.0.113.10",
            behind_tls_reverse_proxy=True,
        )

    with pytest.raises(qs.ExposureError):
        qs.NetworkExposurePolicy(
            bind_mode=qs.BindMode.LOOPBACK_ONLY,
            bind_host="203.0.113.10",
        )
    with pytest.raises(qs.QuackSecurityError, match="plaintext"):
        qs.NetworkExposurePolicy(allow_remote_plaintext=True)


def test_tls_reverse_proxy_mode_still_binds_loopback() -> None:
    pub = qs.publication_gateway_policy(
        bind_mode=qs.BindMode.TLS_REVERSE_PROXY,
        bind_host="127.0.0.1",
    )
    assert pub.network.bind_mode is qs.BindMode.TLS_REVERSE_PROXY
    assert qs.is_loopback_host(pub.network.bind_host)
    with pytest.raises(qs.ExposureError):
        qs.publication_gateway_policy(
            bind_mode=qs.BindMode.TLS_REVERSE_PROXY,
            bind_host="10.0.0.5",
        )


# ---------------------------------------------------------------------------
# Tokens and full SQL handled as sensitive
# ---------------------------------------------------------------------------


def test_tokens_and_full_sql_handled_as_sensitive() -> None:
    token = "super-secret-operation-token-value"
    sql = "SELECT * FROM secrets WHERE token = 'x'"

    assert qs.classify_sensitive("token") is qs.SensitiveClass.SECRET
    assert qs.classify_sensitive("full_sql") is qs.SensitiveClass.SENSITIVE
    assert qs.redact_token(token) == qs.REDACTION_MARKER
    redacted_sql = qs.redact_sql(sql)
    assert token not in redacted_sql
    assert "SELECT" not in redacted_sql
    assert qs.REDACTION_MARKER in redacted_sql
    assert "sql_sha256=" in redacted_sql

    view = qs.sensitive_log_view(token=token, sql=sql, extra={"password": "x", "count": 3})
    rendered = repr(view) + str(view)
    assert token not in rendered
    assert "super-secret" not in rendered
    assert sql not in rendered
    assert view["token"] == qs.REDACTION_MARKER
    assert view["count"] == 3
    assert view["password"] == qs.REDACTION_MARKER

    with pytest.raises(qs.QuackSecurityError, match="sensitive"):
        qs.SensitiveDataPolicy(tokens_are_sensitive=False)
    with pytest.raises(qs.QuackSecurityError, match="sensitive"):
        qs.SensitiveDataPolicy(full_sql_is_sensitive=False)
    with pytest.raises(qs.QuackSecurityError, match="must not be retained"):
        qs.SensitiveDataPolicy(retain_full_sql_in_logs=True)

    # Audit events from callbacks scrub secrets.
    store = qs.OperationCapabilityStore()
    cap = qs.mint_operation_capability(
        operation_id="op-audit",
        profile=qs.ServerProfile.PUBLICATION_GATEWAY,
        canonical_sql=sql,
    )
    store.insert(cap)
    auth = qs.AuthenticationCallback(
        store,
        profile=qs.ServerProfile.PUBLICATION_GATEWAY,
        policy=qs.AuthenticationPolicy(
            mode=qs.AuthenticationMode.ONE_USE_CAPABILITY_CALLBACK,
            callback_name=qs.NON_DEFAULT_AUTH_CALLBACK_NAME,
        ),
    )
    session = auth.authenticate(capability_secret=cap.secret)
    events = auth.audit_events()
    assert events
    blob = repr(events)
    assert cap.secret not in blob
    assert sql not in blob

    authz = qs.AuthorizationCallback(
        auth,
        policy=qs.AuthorizationPolicy(
            mode=qs.AuthorizationMode.EXACT_FULL_SQL,
            callback_name=qs.NON_DEFAULT_AUTHZ_CALLBACK_NAME,
        ),
    )
    authz.authorize(session_id=session.session_id, sql=sql)
    authz_blob = repr(authz.audit_events())
    assert sql not in authz_blob
    assert cap.secret not in authz_blob


# ---------------------------------------------------------------------------
# Guarded launcher plans
# ---------------------------------------------------------------------------


def test_guarded_launcher_builds_distinct_plans() -> None:
    launcher = qs.GuardedServerLauncher()
    pub_cfg = qs.build_guarded_config(qs.ServerProfile.PUBLICATION_GATEWAY)
    owner_cfg = qs.build_guarded_config(
        qs.ServerProfile.CATALOG_OWNER,
        catalog_path=_CATALOG_PATH,
        object_host=_OBJECT.host,
        object_port=_OBJECT.port,
        tls_proxy_host=_TLS_PROXY.host,
        tls_proxy_port=_TLS_PROXY.port,
    )
    pub_plan = launcher.plan(pub_cfg)
    owner_plan = launcher.plan(owner_cfg)

    assert pub_plan.profile is qs.ServerProfile.PUBLICATION_GATEWAY
    assert owner_plan.profile is qs.ServerProfile.CATALOG_OWNER
    assert pub_plan.catalog_path == ""
    assert owner_plan.catalog_path == _CATALOG_PATH
    assert pub_plan.allowed_egress == ()
    assert owner_plan.allowed_egress
    assert "quack" in pub_plan.extension_load_order
    assert "ducklake" not in pub_plan.extension_load_order
    assert owner_plan.extension_load_order == ("quack", "ducklake", "httpfs")
    assert pub_plan.duckdb_settings["enable_external_access"] == "false"
    assert owner_plan.duckdb_settings["enable_external_access"] == "true"
    assert (
        pub_plan.duckdb_settings[qs.QUACK_AUTHENTICATION_FUNCTION]
        == qs.NON_DEFAULT_AUTH_CALLBACK_NAME
    )
    stmts = owner_plan.security_statements()
    assert any("enable_external_access=true" in s for s in stmts)
    assert any("enable_external_access=false" in s for s in pub_plan.security_statements())
    assert any(qs.QUACK_AUTHORIZATION_FUNCTION in s for s in stmts)
    assert stmts[-1] == "SET lock_configuration=true"

    qs.assert_profiles_distinct(pub_plan.policy, owner_plan.policy)

    pub_dict = pub_plan.to_dict()
    assert pub_dict["schema"] == qs.QUACK_SECURITY_SCHEMA
    assert pub_dict["threat_model_schema"] == qs.QUACK_THREAT_MODEL.schema


def test_publication_config_rejects_catalog_and_egress() -> None:
    pub = _publication()
    with pytest.raises(qs.QuackSecurityError, match="catalog_path"):
        qs.GuardedServerConfig(policy=pub, catalog_path=_CATALOG_PATH)
    with pytest.raises(qs.QuackSecurityError, match="object endpoint"):
        qs.GuardedServerConfig(policy=pub, object_endpoint=_OBJECT)


def test_neither_profile_inherits_ambient_reachability() -> None:
    pub = _publication()
    owner = _owner()
    for policy in (pub, owner):
        assert policy.extensions.allow_ambient_extensions is False
        assert policy.extensions.allow_automatic_install is False
        assert policy.extensions.allow_automatic_load is False
        assert policy.filesystem.local_paths.allow_ambient_paths is False
        assert policy.egress.allow_ambient_network is False
        assert policy.os_identity.restricted is True
        assert policy.os_identity.allow_root is False
        assert policy.authentication.per_operation_credentials is True
        assert policy.audit.enabled is True
        assert policy.sensitive.tokens_are_sensitive is True
        assert policy.sensitive.full_sql_is_sensitive is True


def test_os_identity_labels_differ_between_profiles() -> None:
    pub = _publication()
    owner = _owner()
    assert pub.os_identity.identity_label != owner.os_identity.identity_label
    assert "publication" in pub.os_identity.identity_label
    assert "catalog" in owner.os_identity.identity_label


def test_local_path_rejects_remote_uris_and_shared_mounts() -> None:
    with pytest.raises(qs.QuackSecurityError, match="remote/URI"):
        qs.LocalPathPolicy(allowed_paths=("s3://bucket/catalog.duckdb",))
    with pytest.raises(qs.QuackSecurityError, match="remote/URI"):
        qs.LocalPathPolicy(allowed_paths=("https://example/catalog.duckdb",))
    with pytest.raises(qs.QuackSecurityError, match="shared/network"):
        qs.LocalPathPolicy(allowed_paths=("//fileserver/share/catalog.duckdb",))


def test_unknown_session_authorization_fails_closed() -> None:
    launcher = qs.GuardedServerLauncher()
    plan = launcher.plan(qs.build_guarded_config(qs.ServerProfile.PUBLICATION_GATEWAY))
    launcher.install_callbacks(plan)
    with pytest.raises(qs.AuthorizationError, match="unknown"):
        launcher.authorize_sql(
            qs.ServerProfile.PUBLICATION_GATEWAY,
            session_id="sess_missing",
            sql="SELECT 1",
        )


def test_capability_profile_mismatch_rejected() -> None:
    store = qs.OperationCapabilityStore()
    cap = qs.mint_operation_capability(
        operation_id="op-mismatch",
        profile=qs.ServerProfile.PUBLICATION_GATEWAY,
        canonical_sql="SELECT 1",
    )
    store.insert(cap)
    auth = qs.AuthenticationCallback(
        store,
        profile=qs.ServerProfile.CATALOG_OWNER,
        policy=qs.AuthenticationPolicy(
            mode=qs.AuthenticationMode.ONE_USE_CAPABILITY_CALLBACK,
            callback_name=qs.NON_DEFAULT_AUTH_CALLBACK_NAME,
        ),
    )
    with pytest.raises(qs.AuthenticationError, match="profile mismatch"):
        auth.authenticate(capability_secret=cap.secret)
