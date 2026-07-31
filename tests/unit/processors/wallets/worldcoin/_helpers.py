"""Shared helpers for Worldcoin unit tests (not a pytest plugin)."""

from __future__ import annotations

from ipfs_datasets_py.processors.wallets.worldcoin import DEFAULT_WORLD_ID_ACTION


def enabled_env(**overrides: str) -> dict[str, str]:
    env = {
        "WORLD_ID_ENABLED": "1",
        "WORLD_ID_ENVIRONMENT": "staging",
        "WORLD_ID_APP_ID": "app_test_123",
        "WORLD_ID_RP_ID": "rp_test_123",
        "WORLD_ID_RP_SIGNING_KEY": "0x" + "11" * 32,
        "WORLD_ID_NULLIFIER_HMAC_KEY": "nullifier-hmac-secret",
        # Explicit opt-in for legacy fixtures where needed by individual tests.
        "WORLD_ID_ALLOW_LEGACY_PROOFS": "true",
    }
    env.update(overrides)
    return env


def sample_idkit_payload() -> dict[str, object]:
    return {
        "protocol_version": "3.0",
        "nonce": "0xabc123",
        "action": DEFAULT_WORLD_ID_ACTION,
        "environment": "staging",
        "responses": [
            {
                "identifier": "orb",
                "merkle_root": "0xroot",
                "nullifier": "0xnullifier",
                "proof": "0xproof",
                "signal_hash": "0xsignal",
            }
        ],
    }


def sample_idkit_v4_uniqueness_payload() -> dict[str, object]:
    return {
        "protocol_version": "4.0",
        "nonce": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "action": DEFAULT_WORLD_ID_ACTION,
        "action_description": "Attach wallet",
        "environment": "production",
        "user_presence_completed": True,
        "identity_attested": False,
        "integrity_bundle": {
            "version": 1,
            "signature_format": "apple_app_attest",
            "signature": "0xsignature",
            "jwt": "private.jwt.value",
        },
        "responses": [
            {
                "identifier": "proof_of_human",
                "signal_hash": "0x0",
                "proof": ["0x1a", "0x2b", "0x3c", "0x4d", "0x5e"],
                "nullifier": "0xrp-scoped-nullifier",
                "issuer_schema_id": 1,
                "expires_at_min": 1_756_166_400,
            }
        ],
    }


def sample_idkit_v4_session_payload() -> dict[str, object]:
    return {
        "protocol_version": "4.0",
        "nonce": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "session_id": "ses_abc123",
        "environment": "production",
        "user_presence_completed": True,
        "responses": [
            {
                "identifier": "proof_of_human",
                "signal_hash": "0x0",
                "proof": ["0x1a", "0x2b", "0x3c", "0x4d", "0x5e"],
                "session_nullifier": ["0xsession-nullifier", "0xgenerated-action"],
                "issuer_schema_id": 1,
                "expires_at_min": 1_756_166_400,
            }
        ],
    }
