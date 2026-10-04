"""Tests for World ID configuration (WALPROC-G100 / WALPROC-063)."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.processors.wallets.security import endpoint_fingerprint
from ipfs_datasets_py.processors.wallets.worldcoin import (
    DEFAULT_WORLD_ID_ACTION,
    DEFAULT_WORLD_ID_VERIFY_BASE_URL,
    WorldIdConfigError,
    WorldIdSecretConfig,
    load_world_id_config,
)
from ipfs_datasets_py.processors.wallets.worldcoin.config import (
    WORLD_ID_ENDPOINT_POLICY,
    validate_verify_base_url,
    validate_world_id_resolved_addresses,
)
from _helpers import enabled_env


def test_world_id_config_defaults_to_disabled_without_secret_requirements() -> None:
    config = load_world_id_config(env={})

    assert config.enabled is False
    assert config.environment == "staging"
    assert config.default_action == DEFAULT_WORLD_ID_ACTION
    assert config.allowed_actions == (DEFAULT_WORLD_ID_ACTION,)
    assert config.verify_base_url == DEFAULT_WORLD_ID_VERIFY_BASE_URL
    assert config.rp_signature_ttl_seconds == 300
    assert config.http_timeout_seconds == 15.0
    assert config.rp_signing_key.configured is False
    assert config.nullifier_hmac_key.configured is False
    # Safe default rejects legacy evidence unless explicitly permitted.
    assert config.allow_legacy_proofs is False


def test_world_id_config_loads_enabled_backend_settings() -> None:
    config = load_world_id_config(
        env=enabled_env(
            WORLD_ID_ENVIRONMENT="production",
            WORLD_ID_ALLOWED_ACTIONS="wallet-attach-world-id-v1, provider-staff-world-id-v1",
            WORLD_ID_DEFAULT_ACTION="provider-staff-world-id-v1",
            WORLD_ID_CREDENTIAL_POLICY="proof_of_human",
            WORLD_ID_ALLOW_LEGACY_PROOFS="false",
            WORLD_ID_REQUIRE_USER_PRESENCE="true",
            WORLD_ID_RP_SIGNATURE_TTL_SECONDS="120",
            WORLD_ID_VERIFY_BASE_URL="https://developer.world.org/",
            WORLD_ID_HTTP_TIMEOUT_SECONDS="9.5",
        )
    )

    assert config.enabled is True
    assert config.environment == "production"
    assert config.app_id == "app_test_123"
    assert config.rp_id == "rp_test_123"
    assert config.allowed_actions == ("wallet-attach-world-id-v1", "provider-staff-world-id-v1")
    assert config.default_action == "provider-staff-world-id-v1"
    assert config.allow_legacy_proofs is False
    assert config.require_user_presence is True
    assert config.rp_signature_ttl_seconds == 120
    assert config.verify_base_url == "https://developer.world.org"
    assert config.http_timeout_seconds == 9.5
    assert config.rp_signing_key.configured is True
    assert config.nullifier_hmac_key.configured is True


def test_world_id_config_accepts_secret_manager_references_without_secret_values() -> None:
    config = load_world_id_config(
        env=enabled_env(
            WORLD_ID_RP_SIGNING_KEY="",
            WORLD_ID_NULLIFIER_HMAC_KEY="",
            WORLD_ID_RP_SIGNING_KEY_SECRET_REF="secret://wallet/world-id/rp-signing-key",
            WORLD_ID_NULLIFIER_HMAC_KEY_SECRET_REF="secret://wallet/world-id/nullifier-hmac-key",
        )
    )

    assert config.rp_signing_key.value == ""
    assert config.rp_signing_key.secret_ref == "secret://wallet/world-id/rp-signing-key"
    assert config.nullifier_hmac_key.value == ""
    assert config.nullifier_hmac_key.secret_ref == "secret://wallet/world-id/nullifier-hmac-key"
    assert config.rp_signing_key.public_dict() == {"configured": True, "source": "secret_ref"}


def test_world_id_public_config_does_not_expose_secret_values_or_refs() -> None:
    config = load_world_id_config(
        env=enabled_env(
            WORLD_ID_RP_SIGNING_KEY="super-secret-signing-key",
            WORLD_ID_NULLIFIER_HMAC_KEY="super-secret-nullifier-key",
            WORLD_ID_RP_SIGNING_KEY_SECRET_REF="secret://wallet/world-id/rp-signing-key",
            WORLD_ID_NULLIFIER_HMAC_KEY_SECRET_REF="secret://wallet/world-id/nullifier-hmac-key",
        )
    )

    public_payload = json.dumps(config.public_dict(), sort_keys=True)

    assert "super-secret" not in public_payload
    assert "secret://wallet" not in public_payload
    assert "signing_key" not in public_payload.lower()
    assert "nullifier_hmac_key" not in public_payload.lower()
    assert "secret" not in repr(config)


def test_world_id_to_dict_serializes_secret_references_only() -> None:
    config = load_world_id_config(
        env=enabled_env(
            WORLD_ID_RP_SIGNING_KEY="super-secret-signing-key",
            WORLD_ID_NULLIFIER_HMAC_KEY="",
            WORLD_ID_NULLIFIER_HMAC_KEY_SECRET_REF="secret://wallet/world-id/nullifier-hmac-key",
        )
    )

    durable = json.dumps(config.to_dict(), sort_keys=True)
    assert "super-secret-signing-key" not in durable
    assert "secret://wallet/world-id/nullifier-hmac-key" not in durable
    assert config.to_dict()["rp_signing_key"]["kind"] == "direct_secret"
    assert config.to_dict()["nullifier_hmac_key"]["kind"] == "secret_reference"
    assert "reference_id" in config.to_dict()["nullifier_hmac_key"]


def test_world_id_secret_config_repr_str_redact_value_and_secret_ref() -> None:
    """Direct WorldIdSecretConfig repr/str must not leak values or full refs (WALPROC-049)."""

    secret_value = "super-secret-signing-key-value"
    secret_path = "secret://wallet/world-id/rp-signing-key"
    secret = WorldIdSecretConfig(value=secret_value, secret_ref=secret_path)

    rendered_repr = repr(secret)
    rendered_str = str(secret)

    assert secret_value not in rendered_repr
    assert secret_value not in rendered_str
    assert secret_path not in rendered_repr
    assert secret_path not in rendered_str
    assert "secret://" not in rendered_repr
    assert "secret://" not in rendered_str

    # configured/source behavior is preserved and visible on safe surfaces.
    assert secret.configured is True
    assert secret.source == "secret_ref"
    assert secret.public_dict() == {"configured": True, "source": "secret_ref"}
    durable = secret.to_dict()
    assert durable["configured"] is True
    assert durable["source"] == "secret_ref"
    assert durable["kind"] == "secret_reference"
    assert durable["reference_id"] != secret_path
    assert "secret://" not in json.dumps(durable)

    # Repr may report bounded configured/source metadata only.
    assert "configured=True" in rendered_repr
    assert "source='secret_ref'" in rendered_repr
    assert rendered_str == rendered_repr


def test_world_id_secret_config_direct_source_repr_redacts_value() -> None:
    secret_value = "super-secret-nullifier-key"
    secret = WorldIdSecretConfig(value=secret_value, secret_ref="")

    rendered_repr = repr(secret)
    rendered_str = str(secret)

    assert secret_value not in rendered_repr
    assert secret_value not in rendered_str
    assert secret.configured is True
    assert secret.source == "direct"
    assert secret.public_dict() == {"configured": True, "source": "direct"}
    assert secret.to_dict()["kind"] == "direct_secret"
    assert "configured=True" in rendered_repr
    assert "source='direct'" in rendered_repr


def test_world_id_secret_config_unset_repr_is_safe() -> None:
    secret = WorldIdSecretConfig()

    assert secret.configured is False
    assert secret.source == ""
    assert "secret://" not in repr(secret)
    assert "secret://" not in str(secret)
    assert secret.public_dict() == {"configured": False, "source": ""}
    assert secret.to_dict()["kind"] == "unset"


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"WORLD_ID_APP_ID": ""}, "WORLD_ID_APP_ID"),
        ({"WORLD_ID_RP_ID": ""}, "WORLD_ID_RP_ID"),
        ({"WORLD_ID_RP_SIGNING_KEY": "", "WORLD_ID_RP_SIGNING_KEY_SECRET_REF": ""}, "WORLD_ID_RP_SIGNING_KEY"),
        (
            {"WORLD_ID_NULLIFIER_HMAC_KEY": "", "WORLD_ID_NULLIFIER_HMAC_KEY_SECRET_REF": ""},
            "WORLD_ID_NULLIFIER_HMAC_KEY",
        ),
    ],
)
def test_world_id_enabled_config_requires_backend_fields(override: dict[str, str], message: str) -> None:
    with pytest.raises(WorldIdConfigError, match=message):
        load_world_id_config(env=enabled_env(**override))


def test_world_id_config_rejects_browser_exposed_secret_env_vars() -> None:
    with pytest.raises(WorldIdConfigError, match="browser-exposed"):
        load_world_id_config(env={**enabled_env(), "VITE_WORLD_ID_RP_SIGNING_KEY": "leaked"})

    with pytest.raises(WorldIdConfigError, match="browser-exposed"):
        load_world_id_config(env={**enabled_env(), "ABBY_RUNTIME_WORLD_ID_NULLIFIER_HMAC_KEY": "leaked"})


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"WORLD_ID_ENVIRONMENT": "dev"}, "WORLD_ID_ENVIRONMENT"),
        ({"WORLD_ID_ENABLED": "sometimes"}, "WORLD_ID_ENABLED"),
        ({"WORLD_ID_RP_SIGNATURE_TTL_SECONDS": "0"}, "WORLD_ID_RP_SIGNATURE_TTL_SECONDS"),
        ({"WORLD_ID_HTTP_TIMEOUT_SECONDS": "-1"}, "WORLD_ID_HTTP_TIMEOUT_SECONDS"),
        ({"WORLD_ID_VERIFY_BASE_URL": "developer.world.org"}, "WORLD_ID_VERIFY_BASE_URL"),
        ({"WORLD_ID_ALLOWED_ACTIONS": "bad action"}, "actions"),
        (
            {"WORLD_ID_ALLOWED_ACTIONS": DEFAULT_WORLD_ID_ACTION, "WORLD_ID_DEFAULT_ACTION": "other-action"},
            "WORLD_ID_DEFAULT_ACTION",
        ),
        ({"WORLD_ID_APP_ID": "not-app"}, "WORLD_ID_APP_ID"),
        ({"WORLD_ID_RP_ID": "not-rp"}, "WORLD_ID_RP_ID"),
    ],
)
def test_world_id_config_rejects_invalid_values(override: dict[str, str], message: str) -> None:
    with pytest.raises(WorldIdConfigError, match=message):
        load_world_id_config(env=enabled_env(**override))


def test_golden_default_constants(golden_vectors: dict) -> None:
    constants = golden_vectors["default_constants"]
    from ipfs_datasets_py.processors.wallets import worldcoin as package

    assert package.DEFAULT_WORLD_ID_ACTION == constants["DEFAULT_WORLD_ID_ACTION"]
    assert package.DEFAULT_WORLD_ID_VERIFY_BASE_URL == constants["DEFAULT_WORLD_ID_VERIFY_BASE_URL"]
    assert package.DEFAULT_WORLD_ID_SIGNATURE_TTL_SECONDS == constants["DEFAULT_WORLD_ID_SIGNATURE_TTL_SECONDS"]
    assert package.DEFAULT_WORLD_ID_HTTP_TIMEOUT_SECONDS == constants["DEFAULT_WORLD_ID_HTTP_TIMEOUT_SECONDS"]
    assert set(package.SUPPORTED_WORLD_ID_ENVIRONMENTS) == set(constants["SUPPORTED_WORLD_ID_ENVIRONMENTS"])


# --- WALPROC-063: bounded safe verify endpoint policy ---


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "https://169.254.169.254/latest/meta-data",
        "http://169.254.169.254/latest/meta-data",
        "https://metadata.google.internal/",
        "https://127.0.0.1/verify",
        "https://[::1]/verify",
        "https://localhost/verify",
        "https://evil.example/verify",
        "http://developer.world.org/",
        "https://developer.world.org:8443/",
        "https://user:pass@developer.world.org/",
        "https://developer.world.org/?api_key=plaintext",
    ],
)
def test_validate_verify_base_url_rejects_metadata_private_and_non_allowlisted(
    unsafe_url: str,
) -> None:
    with pytest.raises(WorldIdConfigError) as caught:
        validate_verify_base_url(unsafe_url)
    message = str(caught.value)
    assert unsafe_url not in message
    assert "169.254.169.254" not in message
    assert "api_key" not in message
    assert "plaintext" not in message
    assert "user:pass" not in message


def test_validate_verify_base_url_accepts_allowlisted_https_default() -> None:
    assert validate_verify_base_url("https://developer.world.org/") == "https://developer.world.org"
    assert validate_verify_base_url(DEFAULT_WORLD_ID_VERIFY_BASE_URL) == DEFAULT_WORLD_ID_VERIFY_BASE_URL


def test_world_id_config_public_dict_exposes_endpoint_fingerprint_not_raw_url() -> None:
    config = load_world_id_config(env=enabled_env())
    public = config.public_dict()
    durable = config.to_dict()
    rendered = repr(config)

    assert public["verify_endpoint_id"] == endpoint_fingerprint(config.verify_base_url)
    assert "verify_base_url" not in public
    assert DEFAULT_WORLD_ID_VERIFY_BASE_URL not in json.dumps(public)
    assert DEFAULT_WORLD_ID_VERIFY_BASE_URL not in json.dumps(durable)
    assert DEFAULT_WORLD_ID_VERIFY_BASE_URL not in rendered
    assert "verify_endpoint_id" in rendered
    # Runtime attribute remains available for request construction.
    assert config.verify_base_url == DEFAULT_WORLD_ID_VERIFY_BASE_URL


def test_world_id_config_rejects_metadata_service_verify_base_url_from_env() -> None:
    with pytest.raises(WorldIdConfigError) as caught:
        load_world_id_config(
            env=enabled_env(WORLD_ID_VERIFY_BASE_URL="https://169.254.169.254/latest/meta-data")
        )
    assert "169.254.169.254" not in str(caught.value)


def test_world_id_resolved_addresses_reject_dns_rebinding_and_metadata() -> None:
    url = DEFAULT_WORLD_ID_VERIFY_BASE_URL
    with pytest.raises(WorldIdConfigError) as private:
        validate_world_id_resolved_addresses(url, ["1.1.1.1", "127.0.0.1"])
    with pytest.raises(WorldIdConfigError) as metadata:
        validate_world_id_resolved_addresses(url, ["169.254.169.254"])
    with pytest.raises(WorldIdConfigError) as link_local:
        validate_world_id_resolved_addresses(url, ["fe80::1"])

    for exc in (private, metadata, link_local):
        message = str(exc.value)
        assert url not in message
        assert "127.0.0.1" not in message
        assert "169.254.169.254" not in message
        assert "fe80" not in message
        assert "endpoint:" in message

    safe = validate_world_id_resolved_addresses(url, ["1.1.1.1", "8.8.8.8"])
    assert safe == ("1.1.1.1", "8.8.8.8")


def test_world_id_endpoint_policy_is_https_only_allowlist() -> None:
    assert WORLD_ID_ENDPOINT_POLICY.allow_http is False
    assert 443 in WORLD_ID_ENDPOINT_POLICY.allowed_ports
    assert "developer.world.org" in WORLD_ID_ENDPOINT_POLICY.allowed_hosts
