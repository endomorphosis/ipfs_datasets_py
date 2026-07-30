"""WALPROC-G620 World ID old/new differential and fail-closed unsafe baselines.

Proves:

* Safe cryptographic vectors, IDKit shapes, and verify normalizations match
  between ``wallet_interface.world_id`` (pre-move / thin wrapper) and the
  reusable ``ipfs_datasets_py.processors.wallets.worldcoin`` package.
* Legacy and new snapshot envelopes round-trip without raw nullifiers.
* Known unsafe baseline cases from the security freeze now fail closed under
  safe defaults (legacy proofs, unissued challenges, missing presence,
  protocol-correct receipt labels, revoke/expiry invalidation).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.processors.wallets.worldcoin import (
    DEFAULT_WORLD_ID_ACTION,
    DEFAULT_WORLD_ID_VERIFY_BASE_URL,
    WorldIdPayloadError,
    WorldIdVerificationError,
    assert_idkit_allowed_by_config,
    compute_rp_signature_message,
    hash_to_field,
    hash_to_field_hex,
    load_world_id_config,
    normalize_world_id_idkit_response,
    normalize_world_id_verification_response,
    redact_world_id_payload,
    sign_world_id_request,
    verify_world_id_proof,
)
from ipfs_datasets_py.processors.wallets.worldcoin.bindings import (
    WorldIdBindingError,
    WorldIdBindingStore,
)
from ipfs_datasets_py.processors.wallets.worldcoin.challenges import (
    WorldIdChallengeError,
    WorldIdChallengeStore,
)
from ipfs_datasets_py.processors.wallets.worldcoin.processor import WorldIdProcessor
from ipfs_datasets_py.processors.wallets.worldcoin.proofs import (
    create_world_id_proof_receipt,
    proof_system_for_protocol,
    receipt_is_active,
    sanitize_world_id_proof_receipt,
    verifier_id_for_protocol,
)
from ipfs_datasets_py.processors.wallets.worldcoin.snapshots import (
    export_world_id_state,
    import_world_id_state,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
WORLDCOIN_FIXTURES = (
    REPO_ROOT / "ipfs_datasets_py" / "tests" / "fixtures" / "wallets" / "worldcoin"
)
SECURITY_BASELINE = (
    REPO_ROOT
    / "data"
    / "wallet_processor_migration"
    / "audit"
    / "security-baseline.json"
)
REPORT_PATH = (
    REPO_ROOT
    / "data"
    / "wallet_processor_migration"
    / "validation"
    / "conformance-report.json"
)

HMAC_KEY = b"test-only-world-id-state-hmac-key"
OWNER = "did:key:owner"
PROVIDER = {"organization_id": "provider-1", "staff_id": "staff-7"}


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _repo_on_path() -> None:
    root = str(REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def _enabled_env(**overrides: str) -> dict[str, str]:
    env = {
        "WORLD_ID_ENABLED": "1",
        "WORLD_ID_ENVIRONMENT": "staging",
        "WORLD_ID_APP_ID": "app_test_123",
        "WORLD_ID_RP_ID": "rp_test_123",
        "WORLD_ID_RP_SIGNING_KEY": "0x" + "11" * 32,
        "WORLD_ID_NULLIFIER_HMAC_KEY": "nullifier-hmac-secret",
        # Safe default under test: legacy evidence is rejected unless opt-in.
        "WORLD_ID_ALLOW_LEGACY_PROOFS": "false",
    }
    env.update(overrides)
    return env


def _import_old_world_id():
    _repo_on_path()
    try:
        import wallet_interface.world_id as world_id  # type: ignore
    except Exception as exc:  # pragma: no cover - thin wrapper may be absent
        pytest.skip(f"wallet_interface.world_id unavailable for differential: {exc}")
    return world_id


# ---------------------------------------------------------------------------
# Safe vector differential: old thin wrapper vs new package
# ---------------------------------------------------------------------------


def test_safe_hash_and_signing_vectors_match_old_and_new() -> None:
    golden = _load_json(WORLDCOIN_FIXTURES / "golden_vectors.json")
    empty = golden["hash_to_field"]["empty_bytes"]
    action = golden["hash_to_field"]["test_action"]
    signing = golden["rp_signing"]

    # New package recomputes golden vectors.
    assert hash_to_field_hex(b"") == empty["field_hex"]
    assert hash_to_field(b"")[0] == 0
    assert hash_to_field_hex(action["input_utf8"]) == action["field_hex"]

    new_sig = sign_world_id_request(
        signing["signing_key_hex"],
        ttl_seconds=signing["ttl_seconds"],
        random_bytes=bytes.fromhex(signing["random_bytes_hex"]),
        created_at=signing["created_at"],
    )
    without = signing["without_action"]
    assert new_sig.nonce == without["nonce"]
    assert new_sig.signature == without["signature"]
    assert new_sig.to_protocol_dict() == without["protocol_dict"]
    new_message = compute_rp_signature_message(
        without["nonce"],
        signing["created_at"],
        signing["expires_at"],
    )
    assert new_message.hex() == without["message_hex"]

    with_action = signing["with_action_test_action"]
    new_action_sig = sign_world_id_request(
        signing["signing_key_hex"],
        ttl_seconds=signing["ttl_seconds"],
        random_bytes=bytes.fromhex(signing["random_bytes_hex"]),
        created_at=signing["created_at"],
        action=with_action["action"],
    )
    assert new_action_sig.signature == with_action["signature"]

    constants = golden["default_constants"]
    assert DEFAULT_WORLD_ID_ACTION == constants["DEFAULT_WORLD_ID_ACTION"]
    assert DEFAULT_WORLD_ID_VERIFY_BASE_URL == constants["DEFAULT_WORLD_ID_VERIFY_BASE_URL"]

    # Old package must match byte-for-byte on safe vectors.
    old = _import_old_world_id()
    assert old.hash_to_field_hex(b"") == hash_to_field_hex(b"")
    assert old.hash_to_field_hex(action["input_utf8"]) == hash_to_field_hex(
        action["input_utf8"]
    )
    old_sig = old.sign_world_id_request(
        signing["signing_key_hex"],
        ttl_seconds=signing["ttl_seconds"],
        random_bytes=bytes.fromhex(signing["random_bytes_hex"]),
        created_at=signing["created_at"],
    )
    assert old_sig.nonce == new_sig.nonce
    assert old_sig.signature == new_sig.signature
    assert old_sig.to_protocol_dict() == new_sig.to_protocol_dict()
    old_action_sig = old.sign_world_id_request(
        signing["signing_key_hex"],
        ttl_seconds=signing["ttl_seconds"],
        random_bytes=bytes.fromhex(signing["random_bytes_hex"]),
        created_at=signing["created_at"],
        action=with_action["action"],
    )
    assert old_action_sig.signature == new_action_sig.signature
    assert old.DEFAULT_WORLD_ID_ACTION == DEFAULT_WORLD_ID_ACTION
    assert old.DEFAULT_WORLD_ID_VERIFY_BASE_URL == DEFAULT_WORLD_ID_VERIFY_BASE_URL


@pytest.mark.parametrize(
    "fixture_name",
    [
        "idkit_v3_legacy.json",
        "idkit_v4_uniqueness.json",
        "idkit_v4_session.json",
    ],
)
def test_idkit_normalization_matches_old_and_new(fixture_name: str) -> None:
    fixture = _load_json(WORLDCOIN_FIXTURES / fixture_name)
    payload = fixture["payload"]
    expected = fixture["expected_normalization"]

    new_norm = normalize_world_id_idkit_response(payload)
    assert new_norm.protocol_version == expected["protocol_version"]
    assert new_norm.proof_type == expected["proof_type"]
    assert list(new_norm.credential_identifiers) == list(
        expected["credential_identifiers"]
    )
    if "nullifiers" in expected:
        assert list(new_norm.nullifiers) == list(expected["nullifiers"])
    if "session_id" in expected:
        assert new_norm.session_id == expected["session_id"]

    public_json = json.dumps(new_norm.public_dict(), sort_keys=True)
    for token in fixture.get("sensitive_tokens_must_not_appear_in_public_dict", []):
        assert token not in public_json
    for token in fixture.get(
        "sensitive_tokens_must_not_appear_in_repr_or_public_dict", []
    ):
        assert token not in public_json
        assert token not in repr(new_norm)

    old = _import_old_world_id()
    old_norm = old.normalize_idkit_response(payload)
    assert old_norm.protocol_version == new_norm.protocol_version
    assert old_norm.proof_type == new_norm.proof_type
    assert list(old_norm.credential_identifiers) == list(new_norm.credential_identifiers)
    if hasattr(old_norm, "nullifiers") and hasattr(new_norm, "nullifiers"):
        assert list(old_norm.nullifiers) == list(new_norm.nullifiers)


def test_verify_success_and_failure_match_old_and_new() -> None:
    success = _load_json(WORLDCOIN_FIXTURES / "verify_success.json")
    failure = _load_json(WORLDCOIN_FIXTURES / "verify_failure.json")

    new_ok = normalize_world_id_verification_response(success["raw_response"])
    new_bad = normalize_world_id_verification_response(failure["raw_response"])
    assert new_ok.success is True
    assert new_ok.nullifier == success["expected_normalization"]["nullifier"]
    assert new_bad.success is False
    assert new_bad.message == failure["expected_normalization"]["message"]
    assert failure["application_behavior"]["register_world_id_verification_must_raise"]

    old = _import_old_world_id()
    old_ok = old.normalize_world_id_verification_response(success["raw_response"])
    old_bad = old.normalize_world_id_verification_response(failure["raw_response"])
    assert old_ok.success is new_ok.success
    assert old_ok.nullifier == new_ok.nullifier
    assert old_bad.success is new_bad.success
    assert old_bad.message == new_bad.message


def test_redaction_matches_old_and_new() -> None:
    cases = _load_json(WORLDCOIN_FIXTURES / "redaction_cases.json")
    payload = _load_json(WORLDCOIN_FIXTURES / "idkit_v3_legacy.json")["payload"]
    new_redacted = redact_world_id_payload(payload)
    rendered = json.dumps(new_redacted, sort_keys=True)
    case = cases["cases"][0]
    for token in case["must_not_appear_in_redacted_json"]:
        assert token not in rendered
    assert case["expected_redacted_responses_marker"] in rendered

    old = _import_old_world_id()
    old_redacted = old.redact_world_id_payload(payload)
    old_rendered = json.dumps(old_redacted, sort_keys=True)
    for token in case["must_not_appear_in_redacted_json"]:
        assert token not in old_rendered


# ---------------------------------------------------------------------------
# Snapshot differential: old shapes + new state envelope
# ---------------------------------------------------------------------------


def test_legacy_snapshot_import_and_new_export_round_trip() -> None:
    shapes = _load_json(WORLDCOIN_FIXTURES / "snapshot_shapes.json")
    rules = shapes["old_snapshot_import_rules"]
    legacy = shapes["legacy_snapshot_example"]

    store = WorldIdBindingStore(hmac_key=HMAC_KEY)
    import_world_id_state(legacy, store)
    bindings = store.snapshot()["bindings"]
    assert len(bindings) == 1
    binding = bindings[0]
    for field in shapes["world_id_binding_public_fields"]:
        assert field in binding, f"missing public field after import: {field}"
    assert "raw_nullifier" not in binding
    assert binding["nullifier_ref"].startswith(rules["nullifier_ref_prefix"])

    # Wallets without world_id fields must still load.
    empty_store = WorldIdBindingStore(hmac_key=HMAC_KEY)
    import_world_id_state(
        {"schema_version": 1, "wallet_id": "wallet-no-world-id", "wallet": {}},
        empty_store,
    )
    assert empty_store.snapshot()["bindings"] == []

    # New state envelope export/import preserves public binding identity.
    active = WorldIdBindingStore(hmac_key=HMAC_KEY)
    created, _ = active.register(
        wallet_id="wallet-roundtrip",
        actor_did=OWNER,
        rp_id="rp_test_123",
        app_id="app_test_123",
        action=DEFAULT_WORLD_ID_ACTION,
        protocol_version="4.0",
        environment="staging",
        raw_nullifier="raw-nullifier-roundtrip",
        credential_identifiers=["proof_of_human"],
        issuer_schema_ids=[1],
        credential_policy="proof_of_human",
        user_presence_verified=True,
        provider_context=PROVIDER,
    )
    receipt = create_world_id_proof_receipt(created)
    created.proof_receipt_id = receipt.proof_id
    challenges = WorldIdChallengeStore(HMAC_KEY)
    exported = export_world_id_state(
        active,
        wallet_id="wallet-roundtrip",
        challenges=challenges,
        proofs={receipt.proof_id: receipt},
    )
    rendered = json.dumps(exported, sort_keys=True)
    assert "raw-nullifier-roundtrip" not in rendered
    assert exported["version"] == 1

    restored_bindings = WorldIdBindingStore(hmac_key=HMAC_KEY)
    restored_challenges = WorldIdChallengeStore(HMAC_KEY)
    restored_proofs: dict[str, Any] = {}
    import_world_id_state(
        {"world_id_state": exported},
        restored_bindings,
        challenges=restored_challenges,
        proofs=restored_proofs,
    )
    restored = restored_bindings.get(created.binding_id)
    assert restored.to_dict() == created.to_dict()
    assert receipt.proof_id in restored_proofs


# ---------------------------------------------------------------------------
# Known unsafe baseline cases fail closed under safe defaults
# ---------------------------------------------------------------------------


def test_legacy_proofs_fail_closed_by_default() -> None:
    """SEC-WORLDID-LEGACY-DEFAULT-ON: safe defaults reject legacy IDKit evidence."""

    fixture = _load_json(WORLDCOIN_FIXTURES / "idkit_v3_legacy.json")
    normalized = normalize_world_id_idkit_response(fixture["payload"])
    safe_config = load_world_id_config(env=_enabled_env())
    assert safe_config.allow_legacy_proofs is False
    with pytest.raises(WorldIdPayloadError, match="legacy"):
        assert_idkit_allowed_by_config(normalized, safe_config)

    # Explicit opt-in still works for migration windows.
    permissive = load_world_id_config(
        env=_enabled_env(WORLD_ID_ALLOW_LEGACY_PROOFS="true")
    )
    assert permissive.allow_legacy_proofs is True
    assert_idkit_allowed_by_config(normalized, permissive)


def test_unissued_challenge_acceptance_fails_closed() -> None:
    """SEC-WORLDID-UNISSUED-CHALLENGE-ACCEPTANCE: consume requires issued challenge."""

    store = WorldIdChallengeStore(HMAC_KEY)
    with pytest.raises(WorldIdChallengeError):
        store.consume(
            "challenge-was-never-issued",
            nonce="nonce-secret",
            signal="did:key:subject",
            signal_context="wallet_binding",
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


def test_user_presence_requirement_fails_closed() -> None:
    """SEC-WORLDID-UNENFORCED-USER-PRESENCE: presence enforced when configured."""

    fixture = _load_json(WORLDCOIN_FIXTURES / "idkit_v4_uniqueness.json")
    payload = dict(fixture["payload"])
    # Fixture is production; align config environment.
    payload["user_presence_completed"] = False
    normalized = normalize_world_id_idkit_response(payload)
    config = load_world_id_config(
        env=_enabled_env(
            WORLD_ID_ENVIRONMENT=str(payload.get("environment") or "staging"),
            WORLD_ID_REQUIRE_USER_PRESENCE="true",
        )
    )
    with pytest.raises(WorldIdPayloadError, match="user_presence"):
        assert_idkit_allowed_by_config(normalized, config)


def test_protocol_receipt_labels_are_not_hardcoded_v4() -> None:
    """SEC-WORLDID-V3-AS-V4-RECEIPT: receipts track protocol_version."""

    store = WorldIdBindingStore(hmac_key=HMAC_KEY)
    v3_binding, _ = store.register(
        wallet_id="wallet-v3",
        actor_did=OWNER,
        rp_id="rp_test_123",
        app_id="app_test_123",
        action=DEFAULT_WORLD_ID_ACTION,
        protocol_version="3.0",
        environment="staging",
        raw_nullifier="raw-nullifier-v3",
        credential_identifiers=["orb"],
        issuer_schema_ids=[1],
        credential_policy="proof_of_human",
        user_presence_verified=True,
    )
    v4_binding, _ = store.register(
        wallet_id="wallet-v4",
        actor_did=OWNER,
        rp_id="rp_test_123",
        app_id="app_test_123",
        action=DEFAULT_WORLD_ID_ACTION,
        protocol_version="4.0",
        environment="staging",
        raw_nullifier="raw-nullifier-v4",
        credential_identifiers=["proof_of_human"],
        issuer_schema_ids=[1],
        credential_policy="proof_of_human",
        user_presence_verified=True,
    )
    v3_receipt = create_world_id_proof_receipt(v3_binding)
    v4_receipt = create_world_id_proof_receipt(v4_binding)
    assert proof_system_for_protocol("3.0") == "world_id_idkit_v3"
    assert proof_system_for_protocol("4.0") == "world_id_idkit_v4"
    assert v3_receipt.proof_system == "world_id_idkit_v3"
    assert v3_receipt.verifier_id == verifier_id_for_protocol("3.0")
    assert v4_receipt.proof_system == "world_id_idkit_v4"
    assert v4_receipt.verifier_id == verifier_id_for_protocol("4.0")
    # Public sanitation still hides nullifier refs.
    public = sanitize_world_id_proof_receipt(v3_receipt)
    assert "nullifier_ref" not in public.get("public_inputs", {})
    assert "raw-nullifier" not in json.dumps(public)


def test_stale_proof_after_revoke_and_expiry_fails_closed() -> None:
    """SEC-WORLDID-STALE-PROOF-AFTER-REVOKE-EXPIRY."""

    store = WorldIdBindingStore(hmac_key=HMAC_KEY)
    binding, _ = store.register(
        wallet_id="wallet-revoke",
        actor_did=OWNER,
        rp_id="rp_test_123",
        app_id="app_test_123",
        action=DEFAULT_WORLD_ID_ACTION,
        protocol_version="4.0",
        environment="staging",
        raw_nullifier="raw-nullifier-revoke",
        credential_identifiers=["proof_of_human"],
        issuer_schema_ids=[1],
        credential_policy="proof_of_human",
        user_presence_verified=True,
    )
    receipt = create_world_id_proof_receipt(binding)
    binding.proof_receipt_id = receipt.proof_id
    assert receipt_is_active(receipt, binding) is True

    store.revoke(binding.binding_id, reason="user_disconnect")
    revoked = store.get(binding.binding_id)
    assert receipt_is_active(receipt, revoked) is False
    with pytest.raises(WorldIdBindingError, match="revoked"):
        create_world_id_proof_receipt(revoked)

    expired, _ = store.register(
        wallet_id="wallet-expired",
        actor_did="did:key:expired",
        rp_id="rp_test_123",
        app_id="app_test_123",
        action=DEFAULT_WORLD_ID_ACTION,
        protocol_version="4.0",
        environment="staging",
        raw_nullifier="raw-nullifier-expired",
        credential_identifiers=["proof_of_human"],
        issuer_schema_ids=[1],
        credential_policy="proof_of_human",
        user_presence_verified=True,
        expires_at_min=1,
    )
    with pytest.raises(WorldIdBindingError, match="expired"):
        create_world_id_proof_receipt(expired, now_min=2)


def test_processor_rejects_legacy_without_opt_in_and_requires_issued_challenge() -> None:
    config = load_world_id_config(env=_enabled_env())
    processor = WorldIdProcessor(config, hmac_key=HMAC_KEY)
    legacy = _load_json(WORLDCOIN_FIXTURES / "idkit_v3_legacy.json")["payload"]

    with pytest.raises(WorldIdPayloadError, match="legacy"):
        processor.verify_and_bind(
            "wallet-legacy",
            actor_did=OWNER,
            challenge_id="missing",
            signal="did:key:subject",
            signal_context="wallet_binding",
            provider_context=PROVIDER,
            idkit_payload=legacy,
            request_json=lambda *_: {"success": True},
            now=100,
        )

    # v4 path still requires a previously issued challenge.
    v4 = {
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
    with pytest.raises((WorldIdChallengeError, WorldIdBindingError, WorldIdPayloadError)):
        processor.verify_and_bind(
            "wallet-no-challenge",
            actor_did=OWNER,
            challenge_id="never-issued",
            signal="did:key:subject",
            signal_context="wallet_binding",
            provider_context=PROVIDER,
            idkit_payload=v4,
            request_json=lambda *_: {
                "success": True,
                "action": DEFAULT_WORLD_ID_ACTION,
                "environment": "staging",
                "nullifier": "raw-processor-nullifier",
                "results": [{"success": True, "nullifier": "raw-processor-nullifier"}],
            },
            now=100,
        )


def test_unsafe_configurable_endpoints_fail_closed() -> None:
    """SEC-WORLDID-UNSAFE-CONFIGURABLE-ENDPOINTS: local/malformed hosts rejected."""

    payload = _load_json(WORLDCOIN_FIXTURES / "idkit_v4_uniqueness.json")["payload"]
    with pytest.raises(WorldIdVerificationError, match="base URL"):
        verify_world_id_proof(
            "rp_test_123",
            payload,
            verify_base_url="developer.world.org",  # not absolute
            request_json=lambda *_: {},
        )
    # Fail-closed for loopback/private hosts (message may say "not allowed" or "unsafe").
    with pytest.raises(WorldIdVerificationError, match="not allowed|unsafe"):
        verify_world_id_proof(
            "rp_test_123",
            payload,
            verify_base_url="http://localhost:9999",
            request_json=lambda *_: {},
        )
    with pytest.raises(WorldIdVerificationError, match="not allowed|unsafe"):
        verify_world_id_proof(
            "rp_test_123",
            payload,
            verify_base_url="https://127.0.0.1/verify",
            request_json=lambda *_: {},
        )


def test_security_baseline_findings_are_classified_as_failures_not_compatibility() -> None:
    baseline = _load_json(SECURITY_BASELINE)
    assert baseline["policy"]["blessing_as_compatibility_guarantee_forbidden"] is True
    assert baseline["policy"]["default_classification_for_listed_gaps"] == "failure_to_fix"
    terms = {item["acceptance_term"] for item in baseline["findings"]}
    required = {
        "legacy-default-on",
        "unenforced user presence/signal/provider context",
        "unissued challenge acceptance",
        "v3-as-v4 receipt labeling",
        "stale proof receipts after revoke/expiry",
        "unsafe configurable endpoints",
    }
    assert required <= terms
    for finding in baseline["findings"]:
        assert finding["classification"] == "failure_to_fix"
        assert finding["not_compatibility_guarantee"] is True


def test_conformance_report_records_worldcoin_differential_coverage() -> None:
    report = _load_json(REPORT_PATH)
    section = report["worldcoin_differential"]
    assert section["goal_id"] == "WALPROC-G620"
    assert section["safe_vectors_match_old_and_new"] is True
    assert section["snapshots_round_trip"] is True
    assert section["unsafe_baselines_fail_closed"] is True
    assert "legacy_proofs" in section["fail_closed_cases"]
    assert "unissued_challenges" in section["fail_closed_cases"]
    assert "protocol_receipt_labels" in section["fail_closed_cases"]
    assert "revoke_and_expiry" in section["fail_closed_cases"]


def test_no_secret_material_in_public_projections() -> None:
    config = load_world_id_config(
        env=_enabled_env(
            WORLD_ID_RP_SIGNING_KEY="super-secret-signing-key",
            WORLD_ID_NULLIFIER_HMAC_KEY="super-secret-nullifier-key",
        )
    )
    public = json.dumps(config.public_dict(), sort_keys=True)
    assert "super-secret" not in public
    assert "signing_key" not in public.lower()
    assert "nullifier_hmac" not in public.lower()
    assert "super-secret" not in repr(config)
