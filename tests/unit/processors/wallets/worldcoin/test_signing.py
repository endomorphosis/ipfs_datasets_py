"""Tests for World ID hash-to-field and RP signing (WALPROC-G100)."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.processors.wallets.worldcoin import (
    DEFAULT_WORLD_ID_ACTION,
    WorldIdSignatureError,
    compute_rp_signature_message,
    hash_to_field,
    hash_to_field_hex,
    load_world_id_config,
    sign_world_id_request,
    sign_world_id_request_from_config,
)
from _helpers import enabled_env


def test_world_id_hash_to_field_matches_official_empty_string_vector(golden_vectors: dict) -> None:
    expected = golden_vectors["hash_to_field"]["empty_bytes"]["field_hex"]
    assert hash_to_field_hex(b"") == expected
    assert hash_to_field(b"")[0] == 0


def test_world_id_hash_to_field_matches_test_action_vector(golden_vectors: dict) -> None:
    expected = golden_vectors["hash_to_field"]["test_action"]["field_hex"]
    assert hash_to_field_hex("test-action") == expected


def test_world_id_compute_rp_signature_message_matches_official_vector(golden_vectors: dict) -> None:
    rp = golden_vectors["rp_signing"]
    without = rp["without_action"]
    message = compute_rp_signature_message(
        without["nonce"],
        rp["created_at"],
        rp["expires_at"],
    )

    assert len(message) == without["message_length_bytes"]
    assert message.hex() == without["message_hex"]


def test_world_id_compute_rp_signature_message_with_action_is_81_bytes(golden_vectors: dict) -> None:
    rp = golden_vectors["rp_signing"]
    with_action = rp["with_action_test_action"]
    nonce = bytes.fromhex(rp["without_action"]["nonce"].removeprefix("0x"))

    message = compute_rp_signature_message(
        nonce, rp["created_at"], rp["expires_at"], with_action["action"]
    )

    assert len(message) == with_action["message_length_bytes"]
    assert message.hex() == with_action["message_hex"]
    assert message[49:] == hash_to_field("test-action")


def test_world_id_sign_request_matches_official_without_action_vector(golden_vectors: dict) -> None:
    rp = golden_vectors["rp_signing"]
    without = rp["without_action"]
    signature = sign_world_id_request(
        rp["signing_key_hex"],
        ttl_seconds=rp["ttl_seconds"],
        random_bytes=bytes.fromhex(rp["random_bytes_hex"]),
        created_at=rp["created_at"],
    )

    assert signature.nonce == without["nonce"]
    assert signature.created_at == rp["created_at"]
    assert signature.expires_at == rp["expires_at"]
    assert signature.signature == without["signature"]
    assert signature.to_protocol_dict() == without["protocol_dict"]


def test_world_id_sign_request_matches_official_with_action_vector(golden_vectors: dict) -> None:
    rp = golden_vectors["rp_signing"]
    with_action = rp["with_action_test_action"]
    signature = sign_world_id_request(
        rp["signing_key_hex"],
        action=with_action["action"],
        ttl_seconds=rp["ttl_seconds"],
        random_bytes=bytes.fromhex(rp["random_bytes_hex"]),
        created_at=rp["created_at"],
    )

    assert signature.signature == with_action["signature"]
    assert signature.action == with_action["action"]


def test_world_id_sign_request_from_config_uses_allowed_action_and_rp_context() -> None:
    config = load_world_id_config(env=enabled_env(WORLD_ID_RP_SIGNATURE_TTL_SECONDS="300"))

    signature = sign_world_id_request_from_config(
        config,
        action=DEFAULT_WORLD_ID_ACTION,
        random_bytes=bytes(range(32)),
        created_at=1_700_000_000,
    )

    context = signature.to_rp_context(config.rp_id)
    assert context["rp_id"] == "rp_test_123"
    assert context["nonce"] == signature.nonce
    assert context["sig"] == signature.signature
    assert signature.action == DEFAULT_WORLD_ID_ACTION


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"signing_key_hex": "0x1234"}, "signing key"),
        ({"random_bytes": b"short"}, "random_bytes"),
        ({"ttl_seconds": 0}, "ttl_seconds"),
        ({"created_at": -1}, "created_at"),
    ],
)
def test_world_id_sign_request_rejects_invalid_inputs(kwargs: dict[str, object], message: str) -> None:
    params = {
        "signing_key_hex": "0x" + "ab" * 32,
        "random_bytes": bytes(range(32)),
        "created_at": 1_700_000_000,
        "ttl_seconds": 300,
    }
    params.update(kwargs)
    signing_key = str(params.pop("signing_key_hex"))

    with pytest.raises(WorldIdSignatureError, match=message):
        sign_world_id_request(signing_key, **params)  # type: ignore[arg-type]


def test_world_id_sign_from_config_rejects_disabled_unallowed_and_secret_ref_only() -> None:
    disabled = load_world_id_config(env={})
    with pytest.raises(WorldIdSignatureError, match="disabled"):
        sign_world_id_request_from_config(disabled)

    config = load_world_id_config(env=enabled_env())
    with pytest.raises(WorldIdSignatureError, match="not allowed"):
        sign_world_id_request_from_config(config, action="other-action")

    secret_ref_only = load_world_id_config(
        env=enabled_env(
            WORLD_ID_RP_SIGNING_KEY="",
            WORLD_ID_RP_SIGNING_KEY_SECRET_REF="secret://wallet/world-id/rp-signing-key",
            WORLD_ID_NULLIFIER_HMAC_KEY_SECRET_REF="secret://wallet/world-id/nullifier-hmac-key",
        )
    )
    with pytest.raises(WorldIdSignatureError, match="WORLD_ID_RP_SIGNING_KEY"):
        sign_world_id_request_from_config(secret_ref_only)
