"""Tests for IDKit normalization and redaction (WALPROC-G100)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.wallets.worldcoin import (
    DEFAULT_WORLD_ID_ACTION,
    WorldIdPayloadError,
    assert_idkit_allowed_by_config,
    load_world_id_config,
    normalize_idkit_response,
    normalize_world_id_idkit_response,
    redact_world_id_payload,
)
from _helpers import (
    enabled_env,
    sample_idkit_payload,
    sample_idkit_v4_session_payload,
    sample_idkit_v4_uniqueness_payload,
)


def test_world_id_normalizes_v3_legacy_idkit_response() -> None:
    normalized = normalize_idkit_response(sample_idkit_payload())

    assert normalized.protocol_version == "3.0"
    assert normalized.proof_type == "legacy"
    assert normalized.action == DEFAULT_WORLD_ID_ACTION
    assert normalized.environment == "staging"
    assert normalized.credential_identifiers == ("orb",)
    assert normalized.signal_hashes == ("0xsignal",)
    assert normalized.nullifiers == ("0xnullifier",)
    assert normalized.verification_timestamps == ()
    assert normalized.responses[0].credential_identifier == "orb"
    assert normalized.responses[0].issuer_schema_id is None
    assert "0xnullifier" not in repr(normalized)


def test_world_id_normalizes_v4_uniqueness_idkit_response() -> None:
    normalized = normalize_world_id_idkit_response(sample_idkit_v4_uniqueness_payload())

    assert normalized.protocol_version == "4.0"
    assert normalized.proof_type == "uniqueness"
    assert normalized.action == DEFAULT_WORLD_ID_ACTION
    assert normalized.action_description == "Attach wallet"
    assert normalized.user_presence_completed is True
    assert normalized.identity_attested is False
    assert normalized.integrity_bundle_present is True
    assert normalized.credential_identifiers == ("proof_of_human",)
    assert normalized.nullifiers == ("0xrp-scoped-nullifier",)
    assert normalized.signal_hashes == ("0x0",)
    assert normalized.verification_timestamps == (1_756_166_400,)
    assert normalized.responses[0].issuer_schema_id == 1


def test_world_id_normalizes_v4_session_idkit_response() -> None:
    normalized = normalize_idkit_response(sample_idkit_v4_session_payload())

    assert normalized.protocol_version == "4.0"
    assert normalized.proof_type == "session"
    assert normalized.action == ""
    assert normalized.session_id == "ses_abc123"
    assert normalized.credential_identifiers == ("proof_of_human",)
    assert normalized.nullifiers == ("0xsession-nullifier",)
    assert normalized.session_actions == ("0xgenerated-action",)
    assert normalized.verification_timestamps == (1_756_166_400,)


def test_world_id_normalized_public_dict_omits_sensitive_payload_material() -> None:
    normalized = normalize_idkit_response(sample_idkit_v4_uniqueness_payload())

    rendered = json.dumps(normalized.public_dict(), sort_keys=True)

    assert "0xrp-scoped-nullifier" not in rendered
    assert "0x0" not in rendered
    assert "0xsignature" not in rendered
    assert "private.jwt.value" not in rendered
    assert '"nullifier_count": 1' in rendered
    assert '"signal_hash_count": 1' in rendered


def test_fixture_idkit_payloads_match_expected_normalization(fixtures_dir: Path) -> None:
    for name, proof_type in (
        ("idkit_v3_legacy.json", "legacy"),
        ("idkit_v4_uniqueness.json", "uniqueness"),
        ("idkit_v4_session.json", "session"),
    ):
        data = json.loads((fixtures_dir / name).read_text(encoding="utf-8"))
        normalized = normalize_idkit_response(data["payload"])
        expected = data["expected_normalization"]
        assert normalized.proof_type == proof_type
        assert normalized.protocol_version == expected["protocol_version"]
        assert list(normalized.credential_identifiers) == expected["credential_identifiers"]
        assert list(normalized.nullifiers) == expected["nullifiers"]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "JSON object"),
        ({"protocol_version": "2.0", "nonce": "n", "environment": "staging", "responses": [{}]}, "protocol_version"),
        ({"protocol_version": "4.0", "nonce": "n", "environment": "dev", "responses": [{}]}, "environment"),
        ({"protocol_version": "4.0", "nonce": "n", "environment": "staging", "responses": []}, "responses"),
        (
            {
                "protocol_version": "4.0",
                "nonce": "n",
                "environment": "staging",
                "responses": [{"session_nullifier": ["0xsession", "0xaction"]}],
            },
            "session_id",
        ),
        (
            {
                "protocol_version": "4.0",
                "nonce": "n",
                "action": DEFAULT_WORLD_ID_ACTION,
                "environment": "staging",
                "responses": [
                    {
                        "identifier": "proof_of_human",
                        "proof": "0xproof",
                        "nullifier": "0xnullifier",
                        "issuer_schema_id": 1,
                        "expires_at_min": 1_756_166_400,
                    }
                ],
            },
            "proof",
        ),
        (
            {
                "protocol_version": "4.0",
                "nonce": "n",
                "action": DEFAULT_WORLD_ID_ACTION,
                "environment": "staging",
                "responses": [
                    {
                        "identifier": "proof_of_human",
                        "proof": ["0x1", "0x2", "0x3", "0x4", "0x5"],
                        "nullifier": "0xnullifier",
                        "issuer_schema_id": True,
                        "expires_at_min": 1_756_166_400,
                    }
                ],
            },
            "issuer_schema_id",
        ),
        (
            {
                "protocol_version": "3.0",
                "nonce": "n",
                "action": DEFAULT_WORLD_ID_ACTION,
                "environment": "staging",
                "responses": [
                    {"identifier": "orb", "signal_hash": "0xsignal", "proof": "0xproof", "merkle_root": "0xroot"}
                ],
            },
            "nullifier",
        ),
    ],
)
def test_world_id_normalizer_rejects_malformed_or_unsupported_responses(
    payload: object,
    message: str,
) -> None:
    with pytest.raises(WorldIdPayloadError, match=message):
        normalize_idkit_response(payload)  # type: ignore[arg-type]


def test_world_id_payload_redaction_removes_sensitive_proof_values() -> None:
    redacted = redact_world_id_payload(sample_idkit_payload())
    rendered = json.dumps(redacted, sort_keys=True)

    assert "0xproof" not in rendered
    assert "0xnullifier" not in rendered
    assert "0xroot" not in rendered
    assert "0xsignal" not in rendered


def test_safe_defaults_reject_legacy_evidence_unless_explicitly_permitted() -> None:
    legacy = normalize_idkit_response(sample_idkit_payload())
    safe_config = load_world_id_config(env=enabled_env(WORLD_ID_ALLOW_LEGACY_PROOFS="false"))
    with pytest.raises(WorldIdPayloadError, match="legacy"):
        assert_idkit_allowed_by_config(legacy, safe_config)

    permitted = load_world_id_config(env=enabled_env(WORLD_ID_ALLOW_LEGACY_PROOFS="true"))
    assert_idkit_allowed_by_config(legacy, permitted)


def test_require_user_presence_is_enforced() -> None:
    uniqueness = normalize_idkit_response(sample_idkit_v4_uniqueness_payload())
    config = load_world_id_config(
        env=enabled_env(
            WORLD_ID_ENVIRONMENT="production",
            WORLD_ID_REQUIRE_USER_PRESENCE="true",
        )
    )
    assert_idkit_allowed_by_config(uniqueness, config)

    payload = sample_idkit_v4_uniqueness_payload()
    payload["user_presence_completed"] = False
    missing_presence = normalize_idkit_response(payload)
    with pytest.raises(WorldIdPayloadError, match="user_presence"):
        assert_idkit_allowed_by_config(missing_presence, config)
