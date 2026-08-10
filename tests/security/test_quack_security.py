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
"""

from __future__ import annotations

import builtins
import sys
from typing import Any

import pytest

from ipfs_datasets_py.duckdb_control import quack_security as qs


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

CATALOG_PATH = "/var/lib/ducklake/shard-a/catalog.duckdb"
OBJECT_HOST = "objects.shard-a.internal"
OBJECT_PORT = 443
TLS_PROXY_HOST = "tls-proxy.shard-a.internal"
TLS_PROXY_PORT = 8443


def _object_endpoint() -> qs.EgressEndpoint:
    return qs.EgressEndpoint(
        kind=qs.EgressTargetKind.OBJECT_ENDPOINT,
        host=OBJECT_HOST,
        port=OBJECT_PORT,
        use_tls=True,
        path_prefix="/lake/shard-a",
    )


def _tls_proxy_egress() -> qs.EgressEndpoint:
    return qs.EgressEndpoint(
        kind=qs.EgressTargetKind.TLS_PROXY,
        host=TLS_PROXY_HOST,
        port=TLS_PROXY_PORT,
        use_tls=True,
    )


def _catalog_owner(**kwargs: Any) -> qs.QuackSecurityProfileConfig:
    defaults: dict[str, Any] = {
        "catalog_path": CATALOG_PATH,
        "object_endpoint": _object_endpoint(),
        "tls_proxy_egress": _tls_proxy_egress(),
        "identity_name": "quack-catalog-owner",
    }
    defaults.update(kwargs)
    return qs.catalog_owner_profile(**defaults)


def _publication(**kwargs: Any) -> qs.QuackSecurityProfileConfig:
    defaults: dict[str, Any] = {
        "identity_name": "quack-publication-gateway",
    }
    defaults.update(kwargs)
    return qs.publication_gateway_profile(**defaults)


def _owner_launcher(**kwargs: Any) -> qs.GuardedQuackServerLauncher:
    return qs.GuardedQuackServerLauncher(_catalog_owner(), **kwargs)


def _pub_launcher(**kwargs: Any) -> qs.GuardedQuackServerLauncher:
    return qs.GuardedQuackServerLauncher(_publication(), **kwargs)


# ---------------------------------------------------------------------------
# Import-time safety
# ---------------------------------------------------------------------------


def test_quack_security_import_is_side_effect_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Importing quack_security must not import duckdb or open resources."""

    forbidden = {"duckdb", "duckdb.experimental"}
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        root = name.split(".", 1)[0]
        if root in forbidden or name in forbidden:
            raise AssertionError(f"import of {name!r} is forbidden at module import")
        return real_import(name, globals, locals, fromlist, level)

    sys.modules.pop("ipfs_datasets_py.duckdb_control.quack_security", None)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    import ipfs_datasets_py.duckdb_control.quack_security as mod  # noqa: F401

    assert mod.QUACK_SECURITY_SCHEMA.startswith("ipfs_datasets_py/")


# ---------------------------------------------------------------------------
# Threat model
# ---------------------------------------------------------------------------


def test_default_threat_model_covers_both_profiles() -> None:
    model = qs.default_threat_model()
    assert model.schema == qs.QUACK_THREAT_MODEL_SCHEMA
    assert len(model.entries) >= 8
    ids = {e.threat_id for e in model.entries}
    assert "T01" in ids
    assert "T04" in ids  # network eavesdropper / plaintext
    assert "T03" in ids  # reusable token misuse
    # Identity is stable.
    assert model.identity_id() == model.identity_id()
    assert model.identity_id().startswith("sha256:")
    # Assumptions name broker secret retention and profile isolation.
    joined = " ".join(model.assumptions)
    assert "broker" in joined.lower() or "reusable" in joined.lower()
    assert model.non_goals
    public = model.to_dict()
    assert "entries" in public
    assert all("description" in e for e in public["entries"])


def test_threat_model_entry_validation() -> None:
    with pytest.raises(qs.QuackSecurityError):
        qs.ThreatModelEntry(
            threat_id="bad",
            actor=qs.ThreatActor.UNTRUSTED_AGENT,
            asset=qs.ThreatAsset.FULL_SQL_TEXT,
            description="x",
            controls=(qs.ThreatControl.SENSITIVE_REDACTION,),
        )
    with pytest.raises(qs.QuackSecurityError):
        qs.ThreatModelEntry(
            threat_id="T99",
            actor=qs.ThreatActor.UNTRUSTED_AGENT,
            asset=qs.ThreatAsset.FULL_SQL_TEXT,
            description="",
            controls=(qs.ThreatControl.SENSITIVE_REDACTION,),
        )
    with pytest.raises(qs.QuackSecurityError):
        qs.ThreatModelEntry(
            threat_id="T99",
            actor=qs.ThreatActor.UNTRUSTED_AGENT,
            asset=qs.ThreatAsset.FULL_SQL_TEXT,
            description="x",
            controls=(),
        )


# ---------------------------------------------------------------------------
# Default auth/authz never permissive for agent traffic
# ---------------------------------------------------------------------------


def test_default_authentication_and_authorization_never_permissive() -> None:
    # Builders reject PERMISSIVE outright.
    with pytest.raises(qs.QuackSecurityError, match="permissive|PERMISSIVE|agent"):
        _publication(authentication_mode=qs.AuthenticationMode.PERMISSIVE)
    with pytest.raises(qs.QuackSecurityError, match="permissive|PERMISSIVE|agent"):
        _publication(authorization_mode=qs.AuthorizationMode.PERMISSIVE)

    # Default-deny authenticators always deny.
    deny_auth = qs.DefaultDenyAuthenticator()
    assert deny_auth.is_default is True
    assert deny_auth.mode is qs.AuthenticationMode.DEFAULT_DENY
    with pytest.raises(qs.AuthenticationDenied, match="deny"):
        deny_auth.authenticate("any-token")

    deny_authz = qs.DefaultDenyAuthorizer()
    assert deny_authz.is_default is True
    assert deny_authz.mode is qs.AuthorizationMode.DEFAULT_DENY
    with pytest.raises(qs.AuthorizationDenied, match="deny"):
        deny_authz.authorize(session_id="s", sql="SELECT 1")

    # FreshConnectionAuthenticator cannot be constructed as PERMISSIVE.
    store = qs.OneUseCapabilityStore()
    with pytest.raises(qs.QuackSecurityError, match="PERMISSIVE"):
        qs.FreshConnectionAuthenticator(
            store,
            profile=qs.QuackServerProfile.PUBLICATION_GATEWAY,
            mode=qs.AuthenticationMode.PERMISSIVE,
        )


def test_publication_profile_rejects_permissive_config_fields() -> None:
    pub = _publication()
    assert pub.authentication_mode is not qs.AuthenticationMode.PERMISSIVE
    assert pub.authorization_mode is not qs.AuthorizationMode.PERMISSIVE
    assert pub.per_operation_credentials is True
    assert pub.inherit_ambient_filesystem is False
    assert pub.inherit_ambient_extensions is False
    assert pub.inherit_ambient_secrets is False
    assert pub.inherit_ambient_network is False


# ---------------------------------------------------------------------------
# Catalog owner: one-use capability + non-default auth callback
# ---------------------------------------------------------------------------


def test_catalog_owner_requires_one_use_non_default_authentication() -> None:
    with pytest.raises(qs.QuackSecurityError, match="one-use|non-default|callback"):
        _catalog_owner(authentication_mode=qs.AuthenticationMode.DEFAULT_DENY)
    with pytest.raises(qs.QuackSecurityError, match="one-use|non-default|callback"):
        _catalog_owner(authentication_mode=qs.AuthenticationMode.PERMISSIVE)

    owner = _catalog_owner(
        authentication_mode=qs.AuthenticationMode.ONE_USE_CAPABILITY
    )
    assert owner.authentication_mode is qs.AuthenticationMode.ONE_USE_CAPABILITY
    assert owner.authorization_mode is qs.AuthorizationMode.EXACT_FULL_SQL

    owner_proxy = _catalog_owner(
        authentication_mode=qs.AuthenticationMode.AUTHENTICATING_PROXY
    )
    assert owner_proxy.authentication_mode is qs.AuthenticationMode.AUTHENTICATING_PROXY


def test_fresh_catalog_owner_connection_consumes_one_use_capability() -> None:
    launcher = _owner_launcher()
    assert isinstance(launcher.authenticator, qs.FreshConnectionAuthenticator)
    assert launcher.authenticator.is_default is False

    sql = "SELECT snapshot_id FROM lake_meta WHERE catalog = 'shard_a'"
    cap = launcher.issue_operation_capability(
        operation_id="op-owner-1",
        caller_identity="trusted-broker-worker-1",
        sql=sql,
        resource=CATALOG_PATH,
    )
    assert "token=" not in repr(cap) or "***" in repr(cap) or "sha256" in repr(cap)
    assert cap.token not in repr(cap)
    assert sql not in repr(cap)

    session = launcher.authenticate_fresh_connection(cap.token)
    assert session.operation_id == "op-owner-1"
    assert session.caller_identity == "trusted-broker-worker-1"
    assert session.profile is qs.QuackServerProfile.CATALOG_OWNER

    # One-use: replay fails.
    with pytest.raises(
        (qs.AuthenticationDenied, qs.CapabilityAlreadyConsumed, qs.CapabilityNotFound)
    ):
        launcher.authenticate_fresh_connection(cap.token)

    # Exact full-SQL authorization succeeds only for the bound statement.
    authz = launcher.authorize_sql(session_id=session.session_id, sql=sql)
    assert authz["authorized"] is True
    assert sql not in str(authz)  # full SQL redacted in result surface
    assert "sha256" in authz["sql"]

    with pytest.raises(qs.AuthorizationDenied, match="exact full-SQL|does not match"):
        launcher.authorize_sql(
            session_id=session.session_id,
            sql="SELECT * FROM secrets",
        )


def test_capability_expiry_and_profile_mismatch() -> None:
    store = qs.OneUseCapabilityStore()
    now = 1_700_000_000_000
    cap = store.issue(
        operation_id="op-exp",
        profile=qs.QuackServerProfile.CATALOG_OWNER,
        caller_identity="worker",
        ttl_ms=100,
        now_ms=now,
    )
    with pytest.raises(qs.CapabilityExpired):
        store.consume(cap.token, now_ms=now + 1_000)

    cap2 = store.issue(
        operation_id="op-prof",
        profile=qs.QuackServerProfile.CATALOG_OWNER,
        caller_identity="worker",
        ttl_ms=10_000,
        now_ms=now,
    )
    with pytest.raises(qs.AuthenticationDenied, match="profile"):
        store.consume(
            cap2.token,
            expected_profile=qs.QuackServerProfile.PUBLICATION_GATEWAY,
            now_ms=now,
        )


def test_exact_sql_authorizer_rejects_prefix_and_unknown_session() -> None:
    launcher = _owner_launcher()
    sql = "SELECT 1 AS one"
    cap = launcher.issue_operation_capability(
        operation_id="op-exact",
        caller_identity="worker",
        sql=sql,
    )
    session = launcher.authenticate_fresh_connection(cap.token)

    # Prefix match is not enough.
    with pytest.raises(qs.AuthorizationDenied):
        launcher.authorize_sql(session_id=session.session_id, sql="SELECT 1")

    # Unknown session.
    with pytest.raises(qs.AuthorizationDenied, match="unknown|unauthenticated"):
        launcher.authorize_sql(session_id="no-such-session", sql=sql)

    # Multi-statement templates rejected at registration.
    authorizer = launcher.authorizer
    assert isinstance(authorizer, qs.ExactFullSqlAuthorizer)
    with pytest.raises(qs.QuackSecurityError, match="single statement|multi-statement"):
        authorizer.register_exact_sql("op-multi", "SELECT 1; DROP TABLE t")


# ---------------------------------------------------------------------------
# Distinct profile policies
# ---------------------------------------------------------------------------


def test_publication_and_catalog_owner_policies_are_distinct() -> None:
    pub = _publication()
    owner = _catalog_owner()

    assert qs.profiles_are_isolated(pub, owner)

    # External access
    assert pub.external_access.enable_external_access is False
    assert owner.external_access.enable_external_access is True

    # Extensions
    assert pub.extensions.allowed_extensions == ()
    assert set(owner.extensions.allowed_extensions) == {
        "ducklake",
        "quack",
        "httpfs",
    }
    assert pub.extensions.autoinstall_known_extensions is False
    assert owner.extensions.autoload_known_extensions is False

    # Local paths
    assert pub.local_paths.allowed_paths == ()
    assert owner.local_paths.allowed_paths == (CATALOG_PATH,)

    # Filesystem
    assert pub.filesystem.allow_filesystem is False
    assert owner.filesystem.allow_filesystem is True
    assert owner.filesystem.allow_copy is False
    assert owner.filesystem.allow_read_functions is False

    # Egress
    assert pub.egress.allowed_endpoints == ()
    assert len(owner.egress.allowed_endpoints) == 2

    # OS identities
    assert pub.os_identity.identity_name != owner.os_identity.identity_name

    # Serializations differ on the distinct surfaces.
    pub_d = pub.to_dict()
    owner_d = owner.to_dict()
    assert pub_d["external_access"] != owner_d["external_access"]
    assert pub_d["extensions"] != owner_d["extensions"]
    assert pub_d["local_paths"] != owner_d["local_paths"]
    assert pub_d["filesystem"] != owner_d["filesystem"]
    assert pub_d["egress"] != owner_d["egress"]


def test_catalog_owner_exact_path_and_egress_only() -> None:
    owner = _catalog_owner()
    launcher = qs.GuardedQuackServerLauncher(owner)

    # Exact catalog path only.
    launcher.assert_path_policy(CATALOG_PATH)
    with pytest.raises(qs.PolicyViolation, match="local path denied"):
        launcher.assert_path_policy("/var/lib/ducklake/shard-a/other.duckdb")
    with pytest.raises(qs.PolicyViolation):
        launcher.assert_path_policy("/etc/passwd")
    # Prefix is not enough.
    with pytest.raises(qs.PolicyViolation):
        launcher.assert_path_policy("/var/lib/ducklake/shard-a")

    # Exact object endpoint / TLS proxy only.
    launcher.assert_egress_policy(
        host=OBJECT_HOST, port=OBJECT_PORT, use_tls=True, path="/lake/shard-a/file.parquet"
    )
    launcher.assert_egress_policy(
        host=TLS_PROXY_HOST, port=TLS_PROXY_PORT, use_tls=True
    )
    with pytest.raises(qs.PolicyViolation, match="egress denied"):
        launcher.assert_egress_policy(host="evil.example", port=443, use_tls=True)
    with pytest.raises(qs.PolicyViolation):
        launcher.assert_egress_policy(host=OBJECT_HOST, port=80, use_tls=True)
    with pytest.raises(qs.PolicyViolation):
        launcher.assert_egress_policy(
            host=OBJECT_HOST, port=OBJECT_PORT, use_tls=True, path="/other-bucket/x"
        )

    # Pinned extensions only.
    for ext in ("ducklake", "quack", "httpfs"):
        launcher.assert_extension_load(ext)
    with pytest.raises(qs.PolicyViolation, match="extension LOAD denied"):
        launcher.assert_extension_load("vss")
    with pytest.raises(qs.PolicyViolation):
        launcher.assert_extension_load("aws")


def test_publication_gateway_reaches_neither_catalog_nor_object() -> None:
    pub = _publication()
    launcher = qs.GuardedQuackServerLauncher(pub)

    assert pub.local_paths.allowed_paths == ()
    assert pub.egress.allowed_endpoints == ()
    assert pub.external_access.enable_external_access is False
    assert pub.filesystem.allow_filesystem is False

    with pytest.raises(qs.PolicyViolation):
        launcher.assert_path_policy(CATALOG_PATH)
    with pytest.raises(qs.PolicyViolation):
        launcher.assert_egress_policy(host=OBJECT_HOST, port=OBJECT_PORT, use_tls=True)
    with pytest.raises(qs.PolicyViolation):
        launcher.assert_egress_policy(
            host=TLS_PROXY_HOST, port=TLS_PROXY_PORT, use_tls=True
        )
    for ext in ("ducklake", "quack", "httpfs"):
        with pytest.raises(qs.PolicyViolation):
            launcher.assert_extension_load(ext)

    # Launch still succeeds (dry-run) and reaffirms isolation.
    receipt = launcher.launch()
    assert receipt["status"] == "planned"
    plan = receipt["plan"]
    assert plan["profile"]["local_paths"]["allowed_paths"] == []
    assert plan["profile"]["egress"]["allowed_endpoints"] == []
    assert plan["profile"]["extensions"]["allowed_extensions"] == []


def test_publication_cannot_be_built_with_catalog_paths_or_egress() -> None:
    # Direct construction of an inconsistent publication profile fails.
    with pytest.raises(qs.QuackSecurityError, match="publication gateway"):
        qs.QuackSecurityProfileConfig(
            profile=qs.QuackServerProfile.PUBLICATION_GATEWAY,
            os_identity=qs.OsIdentityPolicy(identity_name="pub"),
            bind=qs.BindPolicy(),
            tls_proxy=qs.TlsProxyPolicy(enabled=False),
            extensions=qs.ExtensionPolicy(),
            local_paths=qs.LocalPathPolicy(allowed_paths=(CATALOG_PATH,)),
            filesystem=qs.FilesystemPolicy(allow_filesystem=False),
            egress=qs.EgressPolicy(allowed_endpoints=()),
            external_access=qs.ExternalAccessPolicy(enable_external_access=False),
            authentication_mode=qs.AuthenticationMode.ONE_USE_CAPABILITY,
            authorization_mode=qs.AuthorizationMode.EXACT_FULL_SQL,
        )


# ---------------------------------------------------------------------------
# Remote plaintext rejection
# ---------------------------------------------------------------------------


def test_remote_plaintext_exposure_rejected() -> None:
    with pytest.raises(qs.PlaintextExposureRejected):
        qs.assert_remote_not_plaintext(host="10.0.0.5", use_tls=False)

    with pytest.raises(qs.PlaintextExposureRejected):
        qs.BindPolicy(host="10.0.0.5", port=5433, use_tls=False)

    # Loopback plaintext is allowed (still behind process isolation).
    qs.assert_remote_not_plaintext(host="127.0.0.1", use_tls=False)
    qs.assert_remote_not_plaintext(host="localhost", use_tls=False)
    bind = qs.BindPolicy(host="127.0.0.1", port=5433, use_tls=False)
    assert bind.is_loopback is True

    # Remote with TLS is allowed at the assert level.
    qs.assert_remote_not_plaintext(host="quack.example", use_tls=True)

    # Remote behind TLS proxy (loopback origin) is allowed.
    qs.assert_remote_not_plaintext(
        host="127.0.0.1", use_tls=False, behind_tls_proxy=True
    )

    # Non-loopback egress without TLS rejected.
    with pytest.raises(qs.PlaintextExposureRejected):
        qs.EgressEndpoint(
            kind=qs.EgressTargetKind.OBJECT_ENDPOINT,
            host="objects.example",
            port=80,
            use_tls=False,
        )

    # allow_remote_plaintext flag is hard-forbidden.
    with pytest.raises(qs.QuackSecurityError, match="allow_remote_plaintext"):
        qs.BindPolicy(host="127.0.0.1", allow_remote_plaintext=True)


def test_tls_proxy_requires_loopback_origin_and_tls_termination() -> None:
    with pytest.raises(qs.QuackSecurityError, match="terminate TLS"):
        qs.TlsProxyPolicy(
            enabled=True,
            public_host="pub.example",
            terminate_tls=False,
        )
    with pytest.raises(qs.QuackSecurityError, match="loopback"):
        qs.TlsProxyPolicy(
            enabled=True,
            public_host="pub.example",
            origin_must_be_loopback=False,
        )
    # Publication with TLS proxy for remote use.
    proxy = qs.TlsProxyPolicy(
        enabled=True,
        public_host="publish.example",
        public_port=443,
        require_client_auth=True,
    )
    pub = _publication(tls_proxy=proxy)
    assert pub.tls_proxy.enabled is True
    assert pub.bind.is_loopback is True
    launcher = qs.GuardedQuackServerLauncher(pub)
    receipt = launcher.launch()
    assert receipt["status"] == "planned"


# ---------------------------------------------------------------------------
# Tokens and full SQL are sensitive
# ---------------------------------------------------------------------------


def test_tokens_and_full_sql_handled_as_sensitive() -> None:
    secret_token = "super-secret-operation-capability-token-xyz"
    full_sql = "SELECT secret_col, token FROM authority.wallet_keys WHERE id = 1"

    assert secret_token not in qs.redact_token(secret_token)
    assert "sha256" in qs.redact_token(secret_token)
    assert full_sql not in qs.redact_sql(full_sql)
    assert "sha256" in qs.redact_sql(full_sql)

    payload = {
        "operation_id": "op-1",
        "token": secret_token,
        "sql": full_sql,
        "nested": {"password": "hunter2", "ok": True},
        "rows": [{"quack_token": secret_token, "value": 1}],
    }
    redacted = qs.redact_sensitive(payload)
    blob = str(redacted)
    assert secret_token not in blob
    assert full_sql not in blob
    assert "hunter2" not in blob
    assert redacted["operation_id"] == "op-1"
    assert redacted["nested"]["ok"] is True

    # Capability repr/str scrub the raw token.
    store = qs.OneUseCapabilityStore()
    cap = store.issue(
        operation_id="op-sens",
        profile=qs.QuackServerProfile.CATALOG_OWNER,
        caller_identity="worker",
        token=secret_token,
    )
    assert secret_token not in repr(cap)
    assert secret_token not in str(cap)
    assert secret_token not in str(cap.redacted_dict())

    # Audit events from launcher scrub SQL and tokens.
    events: list[dict[str, Any]] = []
    launcher = _owner_launcher(audit_sink=events.append)
    cap2 = launcher.issue_operation_capability(
        operation_id="op-audit",
        caller_identity="worker",
        sql=full_sql,
    )
    session = launcher.authenticate_fresh_connection(cap2.token)
    launcher.authorize_sql(session_id=session.session_id, sql=full_sql)
    joined = str(events)
    assert secret_token not in joined
    assert full_sql not in joined
    assert cap2.token not in joined

    # Sensitive surface policy cannot disable scrubbing.
    with pytest.raises(qs.QuackSecurityError, match="sensitive"):
        qs.SensitiveSurfacePolicy(tokens_sensitive=False)
    with pytest.raises(qs.QuackSecurityError, match="sensitive"):
        qs.SensitiveSurfacePolicy(full_sql_sensitive=False)
    with pytest.raises(qs.QuackSecurityError, match="scrub"):
        qs.SensitiveSurfacePolicy(scrub_logs=False)


# ---------------------------------------------------------------------------
# Guarded launcher
# ---------------------------------------------------------------------------


def test_guarded_launcher_plans_both_profiles() -> None:
    owner = _owner_launcher()
    pub = _pub_launcher()

    owner_receipt = owner.launch()
    pub_receipt = pub.launch()

    assert owner_receipt["status"] == "planned"
    assert pub_receipt["status"] == "planned"

    owner_plan = owner.plan
    assert owner_plan.authentication_callback == "quack_authentication_function"
    assert owner_plan.authorization_callback == "quack_authorization_function"
    assert set(owner_plan.pre_load_extensions) == {"ducklake", "quack", "httpfs"}
    assert owner_plan.duckdb_config["autoinstall_known_extensions"] == "false"
    assert owner_plan.duckdb_config["autoload_known_extensions"] == "false"
    assert owner_plan.duckdb_config["enable_external_access"] == "true"
    assert owner_plan.duckdb_config["lock_configuration"] == "true"

    pub_plan = pub.plan
    assert pub_plan.pre_load_extensions == ()
    assert pub_plan.duckdb_config["enable_external_access"] == "false"
    assert pub_plan.authentication_callback == "quack_authentication_function"

    # Plans do not embed raw secrets.
    assert "super-secret" not in str(owner_plan.to_dict())


def test_guarded_launcher_with_injected_runner() -> None:
    seen: list[qs.GuardedServerPlan] = []

    def runner(plan: qs.GuardedServerPlan) -> dict[str, Any]:
        seen.append(plan)
        return {"pid": 4242, "token": "should-be-redacted-in-receipt"}

    launcher = _owner_launcher(runner=runner)
    receipt = launcher.launch()
    assert receipt["status"] == "launched"
    assert len(seen) == 1
    assert seen[0].profile_config.profile is qs.QuackServerProfile.CATALOG_OWNER
    # Runner token redacted in receipt.
    assert "should-be-redacted-in-receipt" not in str(receipt)


def test_no_ambient_inheritance_flags() -> None:
    for flag in (
        "inherit_ambient_filesystem",
        "inherit_ambient_extensions",
        "inherit_ambient_secrets",
        "inherit_ambient_network",
    ):
        with pytest.raises(qs.QuackSecurityError, match="ambient"):
            qs.QuackSecurityProfileConfig(
                profile=qs.QuackServerProfile.PUBLICATION_GATEWAY,
                os_identity=qs.OsIdentityPolicy(identity_name="pub"),
                bind=qs.BindPolicy(),
                tls_proxy=qs.TlsProxyPolicy(enabled=False),
                extensions=qs.ExtensionPolicy(),
                local_paths=qs.LocalPathPolicy(),
                filesystem=qs.FilesystemPolicy(),
                egress=qs.EgressPolicy(),
                external_access=qs.ExternalAccessPolicy(),
                authentication_mode=qs.AuthenticationMode.ONE_USE_CAPABILITY,
                authorization_mode=qs.AuthorizationMode.EXACT_FULL_SQL,
                **{flag: True},
            )


def test_os_identity_forbids_root() -> None:
    with pytest.raises(qs.QuackSecurityError, match="root"):
        qs.OsIdentityPolicy(identity_name="root-user", allow_root=True)


def test_extension_policy_forbids_autoload_and_install() -> None:
    with pytest.raises(qs.QuackSecurityError, match="automatic extension"):
        qs.ExtensionPolicy(autoinstall_known_extensions=True)
    with pytest.raises(qs.QuackSecurityError, match="automatic extension"):
        qs.ExtensionPolicy(autoload_known_extensions=True)
    with pytest.raises(qs.QuackSecurityError, match="INSTALL"):
        qs.ExtensionPolicy(allow_install=True)
    with pytest.raises(qs.QuackSecurityError, match="unpinned"):
        qs.ExtensionPolicy(allow_load_unpinned=True)
    with pytest.raises(qs.QuackSecurityError, match="pinned build"):
        qs.ExtensionPolicy(allowed_extensions=("quack",), pinned_builds={})


def test_local_path_policy_rejects_remote_and_ambient() -> None:
    with pytest.raises(qs.QuackSecurityError, match="ambient"):
        qs.LocalPathPolicy(allow_ambient=True)
    with pytest.raises(qs.QuackSecurityError, match="remote|URI"):
        qs.LocalPathPolicy(allowed_paths=("s3://bucket/catalog.duckdb",))
    with pytest.raises(qs.QuackSecurityError, match="remote|URI"):
        qs.LocalPathPolicy(allowed_paths=("https://example/catalog.duckdb",))


def test_build_security_profile_dispatch() -> None:
    pub = qs.build_security_profile("publication_gateway")
    assert pub.profile is qs.QuackServerProfile.PUBLICATION_GATEWAY
    owner = qs.build_security_profile(
        qs.QuackServerProfile.CATALOG_OWNER,
        catalog_path=CATALOG_PATH,
        object_endpoint=_object_endpoint(),
    )
    assert owner.profile is qs.QuackServerProfile.CATALOG_OWNER


def test_catalog_owner_requires_exact_one_catalog_path_and_egress() -> None:
    with pytest.raises(qs.QuackSecurityError, match="exactly one local catalog path"):
        qs.QuackSecurityProfileConfig(
            profile=qs.QuackServerProfile.CATALOG_OWNER,
            os_identity=qs.OsIdentityPolicy(identity_name="owner"),
            bind=qs.BindPolicy(),
            tls_proxy=qs.TlsProxyPolicy(enabled=False),
            extensions=qs.ExtensionPolicy(
                allowed_extensions=qs.CATALOG_OWNER_PINNED_EXTENSIONS,
                pinned_builds={
                    "ducklake": qs.PINNED_DUCKLAKE_EXTENSION_BUILD,
                    "quack": qs.PINNED_QUACK_EXTENSION_BUILD,
                    "httpfs": qs.PINNED_OBJECT_ADAPTER_EXTENSION_BUILD,
                },
            ),
            local_paths=qs.LocalPathPolicy(allowed_paths=()),
            filesystem=qs.FilesystemPolicy(allow_filesystem=True),
            egress=qs.EgressPolicy(allowed_endpoints=(_object_endpoint(),)),
            external_access=qs.ExternalAccessPolicy(enable_external_access=True),
            authentication_mode=qs.AuthenticationMode.ONE_USE_CAPABILITY,
            authorization_mode=qs.AuthorizationMode.EXACT_FULL_SQL,
        )
    # Empty egress is rejected for catalog owners.
    with pytest.raises(qs.QuackSecurityError, match="object endpoint|TLS proxy"):
        qs.QuackSecurityProfileConfig(
            profile=qs.QuackServerProfile.CATALOG_OWNER,
            os_identity=qs.OsIdentityPolicy(identity_name="owner"),
            bind=qs.BindPolicy(),
            tls_proxy=qs.TlsProxyPolicy(enabled=False),
            extensions=qs.ExtensionPolicy(
                allowed_extensions=qs.CATALOG_OWNER_PINNED_EXTENSIONS,
                pinned_builds={
                    "ducklake": qs.PINNED_DUCKLAKE_EXTENSION_BUILD,
                    "quack": qs.PINNED_QUACK_EXTENSION_BUILD,
                    "httpfs": qs.PINNED_OBJECT_ADAPTER_EXTENSION_BUILD,
                },
            ),
            local_paths=qs.LocalPathPolicy(allowed_paths=(CATALOG_PATH,)),
            filesystem=qs.FilesystemPolicy(allow_filesystem=True),
            egress=qs.EgressPolicy(allowed_endpoints=()),
            external_access=qs.ExternalAccessPolicy(enable_external_access=True),
            authentication_mode=qs.AuthenticationMode.ONE_USE_CAPABILITY,
            authorization_mode=qs.AuthorizationMode.EXACT_FULL_SQL,
        )


def test_sql_identity_stable_and_bounded() -> None:
    sql = "SELECT 1"
    assert qs.sql_identity(sql) == qs.sql_identity(sql)
    assert qs.sql_identity(sql) != qs.sql_identity("SELECT 2")
    with pytest.raises(qs.QuackSecurityError):
        qs.sql_identity("x" * (qs.MAX_SQL_BYTES + 1))


def test_is_loopback_host() -> None:
    assert qs.is_loopback_host("127.0.0.1")
    assert qs.is_loopback_host("LOCALHOST")
    assert qs.is_loopback_host("::1")
    assert not qs.is_loopback_host("10.0.0.1")
    assert not qs.is_loopback_host("example.com")


def test_publication_gateway_defaults_to_loopback() -> None:
    pub = _publication()
    assert pub.bind.host in qs.LOOPBACK_HOSTS
    assert pub.bind.port == qs.DEFAULT_QUACK_PORT
    assert pub.per_operation_credentials is True
    assert pub.audit.enabled is True
    assert pub.audit.redact_tokens is True
    assert pub.audit.redact_full_sql is True


def test_module_exports_expected_names() -> None:
    for name in (
        "default_threat_model",
        "publication_gateway_profile",
        "catalog_owner_profile",
        "GuardedQuackServerLauncher",
        "FreshConnectionAuthenticator",
        "ExactFullSqlAuthorizer",
        "OneUseCapabilityStore",
        "assert_remote_not_plaintext",
        "redact_sensitive",
        "profiles_are_isolated",
    ):
        assert name in qs.__all__
        assert hasattr(qs, name)
