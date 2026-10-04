from __future__ import annotations

import json
import threading

import pytest

from ipfs_datasets_py.processors.wallets.worldcoin import DEFAULT_WORLD_ID_ACTION, load_world_id_config
from ipfs_datasets_py.processors.wallets.worldcoin.bindings import (
    WorldIdBindingError,
    WorldIdBindingStore,
)
from ipfs_datasets_py.processors.wallets.worldcoin.challenges import (
    WorldIdChallengeError,
    WorldIdChallengeStore,
    WorldIdReplayError,
)
from ipfs_datasets_py.processors.wallets.worldcoin.processor import WorldIdProcessor
from ipfs_datasets_py.processors.wallets.worldcoin.proofs import (
    create_world_id_proof_receipt,
    receipt_is_active,
    sanitize_world_id_proof_receipt,
)

from ._helpers import enabled_env


HMAC_KEY = b"test-only-world-id-state-hmac-key"
OWNER = "did:key:owner"
PROVIDER = {"organization_id": "provider-1", "staff_id": "staff-7"}


def _register(
    store: WorldIdBindingStore,
    *,
    wallet_id: str = "wallet-1",
    actor_did: str = OWNER,
    raw_nullifier: str = "raw-nullifier-1",
    protocol_version: str = "4.0",
    expires_at_min: int | None = None,
):
    return store.register(
        wallet_id=wallet_id,
        actor_did=actor_did,
        rp_id="rp_test_123",
        app_id="app_test_123",
        action=DEFAULT_WORLD_ID_ACTION,
        protocol_version=protocol_version,
        environment="staging",
        raw_nullifier=raw_nullifier,
        credential_identifiers=["proof_of_human", "proof_of_human"],
        issuer_schema_ids=[1, 1],
        credential_policy="proof_of_human",
        user_presence_verified=True,
        provider_context=PROVIDER,
        expires_at_min=expires_at_min,
    )


def test_challenge_binds_every_context_field_and_persists_only_hmac_commitments() -> None:
    store = WorldIdChallengeStore(HMAC_KEY)
    challenge = store.issue(
        nonce="nonce-secret",
        signal="did:key:subject",
        signal_context="provider_staff_verification",
        action=DEFAULT_WORLD_ID_ACTION,
        environment="staging",
        credential_policy="proof_of_human",
        require_user_presence=True,
        protocol_version="4.0",
        actor_did=OWNER,
        provider_context=PROVIDER,
        ttl_seconds=60,
        now=100,
    )

    wrong_context = {**PROVIDER, "staff_id": "staff-8"}
    with pytest.raises(WorldIdChallengeError, match="context"):
        store.consume(
            challenge.challenge_id,
            nonce="nonce-secret",
            signal="did:key:subject",
            signal_context="provider_staff_verification",
            action=DEFAULT_WORLD_ID_ACTION,
            environment="staging",
            credential_policy="proof_of_human",
            user_presence_completed=True,
            protocol_version="4.0",
            actor_did=OWNER,
            provider_context=wrong_context,
            replay_value="raw-nullifier-secret",
            now=101,
        )

    consumed = store.consume(
        challenge.challenge_id,
        nonce="nonce-secret",
        signal="did:key:subject",
        signal_context="provider_staff_verification",
        action=DEFAULT_WORLD_ID_ACTION,
        environment="staging",
        credential_policy="proof_of_human",
        user_presence_completed=True,
        protocol_version="4.0",
        actor_did=OWNER,
        provider_context=PROVIDER,
        replay_value="raw-nullifier-secret",
        now=101,
    )
    snapshot = store.snapshot()
    rendered = json.dumps(snapshot, sort_keys=True)

    assert consumed.status == "consumed"
    assert "nonce-secret" not in rendered
    assert "raw-nullifier-secret" not in rendered
    assert consumed.nonce_commitment.startswith("hmac-sha256:")
    assert all(key.startswith("hmac-sha256:") for key in snapshot["replay_commitments"])

    restored = WorldIdChallengeStore(HMAC_KEY)
    restored.restore(snapshot)
    with pytest.raises(WorldIdReplayError, match="already consumed"):
        restored.consume(
            challenge.challenge_id,
            nonce="nonce-secret",
            signal="did:key:subject",
            signal_context="provider_staff_verification",
            action=DEFAULT_WORLD_ID_ACTION,
            environment="staging",
            credential_policy="proof_of_human",
            user_presence_completed=True,
            protocol_version="4.0",
            actor_did=OWNER,
            provider_context=PROVIDER,
            replay_value="raw-nullifier-secret",
            now=102,
        )


def test_binding_replay_uniqueness_is_atomic_and_survives_snapshot() -> None:
    store = WorldIdBindingStore(hmac_key=HMAC_KEY)
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def register(wallet_id: str, actor_did: str) -> None:
        barrier.wait()
        try:
            _register(store, wallet_id=wallet_id, actor_did=actor_did)
            outcomes.append("created")
        except WorldIdBindingError:
            outcomes.append("replayed")

    threads = [
        threading.Thread(target=register, args=("wallet-1", OWNER)),
        threading.Thread(target=register, args=("wallet-2", "did:key:other")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["created", "replayed"]
    snapshot = store.snapshot()
    rendered = json.dumps(snapshot, sort_keys=True)
    assert "raw-nullifier-1" not in rendered
    assert len(snapshot["replay_commitments"]) == 1

    restored = WorldIdBindingStore(hmac_key=HMAC_KEY)
    restored.restore(snapshot)
    with pytest.raises(WorldIdBindingError, match="raw nullifier"):
        _register(restored, wallet_id="wallet-3", actor_did="did:key:third")

    sanitized_store = WorldIdBindingStore(hmac_key=HMAC_KEY)
    sanitized, _ = sanitized_store.register(
        wallet_id="wallet-sanitized",
        actor_did=OWNER,
        rp_id="rp_test_123",
        action=DEFAULT_WORLD_ID_ACTION,
        protocol_version="4.0",
        environment="staging",
        raw_nullifier="never-persist-this",
        metadata={
            "purpose": "wallet binding",
            "raw_nullifier": "never-persist-this",
            "nested": {"proof": "0xsecret-proof"},
        },
    )
    assert sanitized.metadata == {"purpose": "wallet binding", "nested": {}}
    assert "never-persist-this" not in json.dumps(sanitized_store.snapshot())


def test_receipts_track_protocol_and_binding_liveness_and_projection_authorization() -> None:
    store = WorldIdBindingStore(hmac_key=HMAC_KEY)
    binding, created = _register(store, protocol_version="3.0")
    assert created is True

    receipt = create_world_id_proof_receipt(binding)
    binding.proof_receipt_id = receipt.proof_id
    public = sanitize_world_id_proof_receipt(receipt)

    assert receipt.proof_system == "world_id_idkit_v3"
    assert receipt.verifier_id == "world_id_developer_portal_v3"
    assert receipt.circuit_id == "world-id-idkit-v3-developer-portal"
    assert public["public_inputs"]["nullifier_commitment"].startswith("hmac-sha256:")
    assert "nullifier_ref" not in public["public_inputs"]
    assert receipt_is_active(receipt, binding)

    with pytest.raises(WorldIdBindingError, match="not authorized"):
        store.minimum_projection(
            binding.binding_id,
            caller_did="did:key:stranger",
            authorize=lambda *_: False,
        )
    projection = store.minimum_projection(
        binding.binding_id,
        caller_did=OWNER,
        authorize=lambda caller, value: caller == value.actor_did,
    )
    assert "nullifier_ref" not in projection
    assert "provider_context" not in projection

    store.revoke(binding.binding_id, reason="disconnected")
    assert receipt_is_active(receipt, binding) is False
    with pytest.raises(WorldIdBindingError, match="revoked"):
        create_world_id_proof_receipt(binding)

    expired, _ = _register(
        store,
        wallet_id="wallet-expired",
        actor_did="did:key:expired",
        raw_nullifier="raw-nullifier-expired",
        expires_at_min=1,
    )
    with pytest.raises(WorldIdBindingError, match="expired"):
        create_world_id_proof_receipt(expired, now_min=2)


def test_processor_verifies_issued_challenge_and_round_trips_state() -> None:
    config = load_world_id_config(env=enabled_env(WORLD_ID_REQUIRE_USER_PRESENCE="true"))
    processor = WorldIdProcessor(config)
    payload = {
        "protocol_version": "4.0",
        "nonce": "nonce-processor",
        "action": DEFAULT_WORLD_ID_ACTION,
        "environment": "staging",
        "user_presence_completed": True,
        "responses": [
            {
                "identifier": "proof_of_human",
                "signal_hash": "0xsignal",
                "proof": ["0x1", "0x2", "0x3", "0x4", "0x5"],
                "nullifier": "raw-processor-nullifier",
                "issuer_schema_id": 1,
                "expires_at_min": 1_756_166_400,
            }
        ],
    }
    challenge = processor.issue_challenge(
        nonce="nonce-processor",
        signal="did:key:subject",
        signal_context="wallet_binding",
        actor_did=OWNER,
        provider_context=PROVIDER,
        now=100,
    )

    def verify(*_):
        return {
            "success": True,
            "action": DEFAULT_WORLD_ID_ACTION,
            "environment": "staging",
            "nullifier": "raw-processor-nullifier",
            "created_at": "2026-07-29T00:00:00Z",
            "results": [{"success": True, "nullifier": "raw-processor-nullifier"}],
        }

    result = processor.verify_and_bind(
        "wallet-processor",
        actor_did=OWNER,
        challenge_id=challenge.challenge_id,
        signal="did:key:subject",
        signal_context="wallet_binding",
        provider_context=PROVIDER,
        idkit_payload=payload,
        request_json=verify,
        now=101,
    )
    snapshot = processor.snapshot(wallet_id="wallet-processor")
    rendered = json.dumps(snapshot, sort_keys=True)

    assert result.binding.challenge_id == challenge.challenge_id
    assert result.binding.user_presence_verified is True
    assert result.binding.provider_context == PROVIDER
    assert result.proof.proof_system == "world_id_idkit_v4"
    assert "raw-processor-nullifier" not in rendered
    assert "nonce-processor" not in rendered

    restored = WorldIdProcessor(config)
    restored.restore(snapshot)
    assert restored.bindings.get(result.binding.binding_id).to_dict() == result.binding.to_dict()
    assert restored.proofs[result.proof.proof_id].to_dict() == result.proof.to_dict()
