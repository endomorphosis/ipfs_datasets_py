"""Tests for Developer Portal verification (WALPROC-G100)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.wallets.worldcoin import (
    DEFAULT_WORLD_ID_ACTION,
    WorldIdVerificationError,
    load_world_id_config,
    normalize_world_id_verification_response,
    verify_world_id_proof,
    verify_world_id_proof_from_config,
)
from _helpers import enabled_env, sample_idkit_payload


def test_world_id_verify_client_posts_payload_as_is_and_normalizes_response() -> None:
    payload = sample_idkit_payload()
    calls: list[tuple[str, str, object, dict[str, str], float]] = []

    def fake_request_json(method, url, request_payload, headers, timeout_seconds):
        calls.append((method, url, request_payload, dict(headers), timeout_seconds))
        assert request_payload is payload
        return {
            "success": True,
            "results": [
                {
                    "identifier": "orb",
                    "success": True,
                    "nullifier": "0xverified-nullifier",
                    "code": "ok",
                    "detail": "verified",
                }
            ],
            "action": DEFAULT_WORLD_ID_ACTION,
            "created_at": "2026-06-13T00:00:00Z",
            "environment": "staging",
            "session_id": "session-123",
            "message": "verified",
        }

    result = verify_world_id_proof(
        "rp_test_123",
        payload,
        verify_base_url="https://developer.world.org/",
        timeout_seconds=9.5,
        request_json=fake_request_json,
    )

    assert calls == [
        (
            "POST",
            "https://developer.world.org/api/v4/verify/rp_test_123",
            payload,
            {"content-type": "application/json"},
            9.5,
        )
    ]
    assert result.success is True
    assert result.action == DEFAULT_WORLD_ID_ACTION
    assert result.nullifier == "0xverified-nullifier"
    assert result.created_at == "2026-06-13T00:00:00Z"
    assert result.environment == "staging"
    assert result.session_id == "session-123"
    assert len(result.successful_results) == 1


def test_world_id_verify_from_config_uses_rp_and_timeout() -> None:
    config = load_world_id_config(env=enabled_env(WORLD_ID_HTTP_TIMEOUT_SECONDS="4.25"))
    seen: dict[str, object] = {}

    def fake_request_json(method, url, request_payload, headers, timeout_seconds):
        seen.update(url=url, timeout=timeout_seconds)
        return {"success": True, "results": [], "action": DEFAULT_WORLD_ID_ACTION, "nullifier": "0xabc"}

    result = verify_world_id_proof_from_config(config, sample_idkit_payload(), request_json=fake_request_json)

    assert result.success is True
    assert seen == {"url": "https://developer.world.org/api/v4/verify/rp_test_123", "timeout": 4.25}


def test_world_id_verify_rejects_disabled_config_and_bad_inputs() -> None:
    with pytest.raises(WorldIdVerificationError, match="disabled"):
        verify_world_id_proof_from_config(load_world_id_config(env={}), sample_idkit_payload())

    with pytest.raises(WorldIdVerificationError, match="rp_id"):
        verify_world_id_proof("", sample_idkit_payload(), request_json=lambda *_: {})

    with pytest.raises(WorldIdVerificationError, match="base URL"):
        verify_world_id_proof("rp_test_123", sample_idkit_payload(), verify_base_url="developer.world.org")

    with pytest.raises(WorldIdVerificationError, match="timeout_seconds"):
        verify_world_id_proof("rp_test_123", sample_idkit_payload(), timeout_seconds=0)

    with pytest.raises(WorldIdVerificationError, match="not allowed"):
        verify_world_id_proof(
            "rp_test_123",
            sample_idkit_payload(),
            verify_base_url="http://localhost:9999",
            request_json=lambda *_: {},
        )


def test_world_id_verify_rejects_malformed_response() -> None:
    with pytest.raises(WorldIdVerificationError, match="JSON object"):
        normalize_world_id_verification_response([])  # type: ignore[arg-type]

    with pytest.raises(WorldIdVerificationError, match="results"):
        normalize_world_id_verification_response({"success": True, "results": {"bad": "shape"}})


def test_world_id_verify_errors_redact_proof_payload_material() -> None:
    def fake_request_json(*_):
        raise RuntimeError("upstream failed proof=0xproof nullifier=0xnullifier")

    with pytest.raises(WorldIdVerificationError) as exc_info:
        verify_world_id_proof("rp_test_123", sample_idkit_payload(), request_json=fake_request_json)

    message = str(exc_info.value)
    assert "[redacted World ID verification error]" in message
    assert "0xproof" not in message
    assert "0xnullifier" not in message


def test_verify_fixture_success_and_failure_shapes(fixtures_dir: Path) -> None:
    success = json.loads((fixtures_dir / "verify_success.json").read_text(encoding="utf-8"))
    failure = json.loads((fixtures_dir / "verify_failure.json").read_text(encoding="utf-8"))

    ok = normalize_world_id_verification_response(success["raw_response"])
    expected_ok = success["expected_normalization"]
    assert ok.success is expected_ok["success"]
    assert ok.nullifier == expected_ok["nullifier"]
    assert len(ok.successful_results) == expected_ok["successful_results_count"]
    public = json.dumps(ok.public_dict())
    assert "0xverified-nullifier" not in public
    assert ok.public_dict()["has_nullifier"] is True
    assert all(result.get("nullifier") == "[redacted]" for result in ok.public_dict()["results"])  # type: ignore[union-attr]

    bad = normalize_world_id_verification_response(failure["raw_response"])
    assert bad.success is False
    assert len(bad.successful_results) == 0
