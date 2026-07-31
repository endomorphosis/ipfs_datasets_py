"""Tests for Developer Portal verification (WALPROC-G100 / WALPROC-063)."""

from __future__ import annotations

import gzip
import io
import json
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request

import pytest

from ipfs_datasets_py.processors.wallets.security import endpoint_fingerprint
from ipfs_datasets_py.processors.wallets.worldcoin import (
    DEFAULT_WORLD_ID_ACTION,
    DEFAULT_WORLD_ID_VERIFY_BASE_URL,
    WorldIdVerificationError,
    load_world_id_config,
    normalize_world_id_verification_response,
    verify_world_id_proof,
    verify_world_id_proof_from_config,
)
from ipfs_datasets_py.processors.wallets.worldcoin.developer_portal import (
    WorldIdTransportLimits,
    WorldIdVerificationResult,
    build_world_id_request_json,
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

    with pytest.raises(WorldIdVerificationError, match="not allowed|unsafe|scheme"):
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
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


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


# --- WALPROC-063: bounded transport and identity-boundary regressions ---


VERIFY_URL = f"{DEFAULT_WORLD_ID_VERIFY_BASE_URL}/api/v4/verify/rp_test_123"
PUBLIC_ADDRESS = "1.1.1.1"


class _FakeResponse:
    def __init__(
        self,
        body: bytes,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._buffer = io.BytesIO(body)
        self.status = status
        self.code = status
        self.headers = headers or {"content-type": "application/json"}

    def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _json_body(payload: dict[str, object]) -> bytes:
    return json.dumps(payload).encode("utf-8")


def test_default_transport_rejects_metadata_service_url_before_io() -> None:
    opened: list[object] = []

    def fake_open(request: urllib_request.Request, *, timeout: float) -> _FakeResponse:
        opened.append(request)
        return _FakeResponse(b"{}")

    transport = build_world_id_request_json(
        address_resolver=lambda host, port: (PUBLIC_ADDRESS,),
        urlopen=fake_open,
    )
    with pytest.raises(WorldIdVerificationError) as caught:
        transport(
            "POST",
            "https://169.254.169.254/latest/meta-data",
            {},
            {"content-type": "application/json"},
            5.0,
        )
    assert opened == []
    assert "169.254.169.254" not in str(caught.value)


def test_default_transport_rejects_dns_rebinding_to_private_or_metadata() -> None:
    opened: list[object] = []

    def fake_open(request: urllib_request.Request, *, timeout: float) -> _FakeResponse:
        opened.append(request)
        return _FakeResponse(b"{}")

    for answers in (("127.0.0.1",), ("169.254.169.254",), (PUBLIC_ADDRESS, "10.0.0.1")):
        transport = build_world_id_request_json(
            address_resolver=lambda host, port, resolved=answers: resolved,
            urlopen=fake_open,
        )
        with pytest.raises(WorldIdVerificationError) as caught:
            transport(
                "POST",
                VERIFY_URL,
                {"action": DEFAULT_WORLD_ID_ACTION},
                {"content-type": "application/json"},
                5.0,
            )
        message = str(caught.value)
        assert "DNS" in message or "unsafe" in message or "endpoint:" in message
        assert "127.0.0.1" not in message
        assert "169.254.169.254" not in message
        assert "10.0.0.1" not in message
        assert VERIFY_URL not in message
    assert opened == []


def test_default_transport_rejects_redirect_responses() -> None:
    def redirect_open(request: urllib_request.Request, *, timeout: float) -> _FakeResponse:
        return _FakeResponse(
            b"",
            status=302,
            headers={"location": "https://evil.example/capture", "content-type": "text/plain"},
        )

    transport = build_world_id_request_json(
        address_resolver=lambda host, port: (PUBLIC_ADDRESS,),
        urlopen=redirect_open,
    )
    with pytest.raises(WorldIdVerificationError, match="redirect") as caught:
        transport(
            "POST",
            VERIFY_URL,
            {"action": DEFAULT_WORLD_ID_ACTION},
            {"content-type": "application/json"},
            5.0,
        )
    message = str(caught.value)
    assert "evil.example" not in message
    assert VERIFY_URL not in message
    assert endpoint_fingerprint(VERIFY_URL).split(":", 1)[1] in message or "endpoint:" in message


def test_default_transport_rejects_http_error_redirect_status() -> None:
    def redirect_error(request: urllib_request.Request, *, timeout: float) -> _FakeResponse:
        raise urllib_error.HTTPError(
            VERIFY_URL,
            301,
            "Moved",
            hdrs={"location": "https://169.254.169.254/"},  # type: ignore[arg-type]
            fp=io.BytesIO(b"moved"),
        )

    transport = build_world_id_request_json(
        address_resolver=lambda host, port: (PUBLIC_ADDRESS,),
        urlopen=redirect_error,
    )
    with pytest.raises(WorldIdVerificationError, match="redirect") as caught:
        transport(
            "POST",
            VERIFY_URL,
            {"action": DEFAULT_WORLD_ID_ACTION},
            {"content-type": "application/json"},
            5.0,
        )
    assert "169.254.169.254" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_default_transport_rejects_oversized_and_compressed_bomb_bodies() -> None:
    limits = WorldIdTransportLimits(
        max_request_bytes=1_024,
        max_response_bytes=64,
        max_decompressed_bytes=64,
        max_attempts=1,
        request_timeout_seconds=5.0,
    )

    def oversized_open(request: urllib_request.Request, *, timeout: float) -> _FakeResponse:
        return _FakeResponse(b"x" * 128)

    transport = build_world_id_request_json(
        address_resolver=lambda host, port: (PUBLIC_ADDRESS,),
        urlopen=oversized_open,
        limits=limits,
    )
    with pytest.raises(WorldIdVerificationError, match="byte budget") as oversized:
        transport(
            "POST",
            VERIFY_URL,
            {"action": DEFAULT_WORLD_ID_ACTION},
            {"content-type": "application/json"},
            5.0,
        )
    assert VERIFY_URL not in str(oversized.value)

    compressed = gzip.compress(b"y" * 256)

    def compressed_open(request: urllib_request.Request, *, timeout: float) -> _FakeResponse:
        return _FakeResponse(
            compressed,
            headers={"content-type": "application/json", "content-encoding": "gzip"},
        )

    transport = build_world_id_request_json(
        address_resolver=lambda host, port: (PUBLIC_ADDRESS,),
        urlopen=compressed_open,
        limits=limits,
    )
    with pytest.raises(WorldIdVerificationError, match="decompression budget") as bomb:
        transport(
            "POST",
            VERIFY_URL,
            {"action": DEFAULT_WORLD_ID_ACTION},
            {"content-type": "application/json"},
            5.0,
        )
    assert VERIFY_URL not in str(bomb.value)


def test_default_transport_rejects_oversized_request_body() -> None:
    limits = WorldIdTransportLimits(
        max_request_bytes=16,
        max_response_bytes=1_024,
        max_decompressed_bytes=1_024,
        max_attempts=1,
        request_timeout_seconds=5.0,
    )
    opened: list[object] = []

    def fake_open(request: urllib_request.Request, *, timeout: float) -> _FakeResponse:
        opened.append(request)
        return _FakeResponse(b"{}")

    transport = build_world_id_request_json(
        address_resolver=lambda host, port: (PUBLIC_ADDRESS,),
        urlopen=fake_open,
        limits=limits,
    )
    with pytest.raises(WorldIdVerificationError, match="request exceeded"):
        transport(
            "POST",
            VERIFY_URL,
            {"action": "a" * 64},
            {"content-type": "application/json"},
            5.0,
        )
    assert opened == []


def test_default_transport_success_path_parses_json_under_bounds() -> None:
    payload = {"success": True, "results": [], "action": DEFAULT_WORLD_ID_ACTION, "nullifier": "0xabc"}

    def fake_open(request: urllib_request.Request, *, timeout: float) -> _FakeResponse:
        assert request.get_method() == "POST"
        assert request.full_url == VERIFY_URL
        return _FakeResponse(_json_body(payload))

    transport = build_world_id_request_json(
        address_resolver=lambda host, port: (PUBLIC_ADDRESS,),
        urlopen=fake_open,
    )
    result = transport(
        "POST",
        VERIFY_URL,
        {"action": DEFAULT_WORLD_ID_ACTION},
        {"content-type": "application/json"},
        5.0,
    )
    assert result["success"] is True
    assert result["nullifier"] == "0xabc"


def test_verify_endpoint_leak_errors_use_fingerprint_only() -> None:
    unsafe = "https://169.254.169.254/latest/meta-data"
    with pytest.raises(WorldIdVerificationError) as caught:
        verify_world_id_proof(
            "rp_test_123",
            sample_idkit_payload(),
            verify_base_url=unsafe,
            request_json=lambda *_: {},
        )
    message = str(caught.value)
    assert unsafe not in message
    assert "169.254.169.254" not in message
    assert "meta-data" not in message


def test_verify_exception_chain_is_sanitized() -> None:
    secret_url = "https://attacker.example/steal?token=super-secret"

    def fake_request_json(*_):
        raise ConnectionError(f"failed connecting to {secret_url} proof=0xdead")

    with pytest.raises(WorldIdVerificationError) as caught:
        verify_world_id_proof(
            "rp_test_123",
            sample_idkit_payload(),
            request_json=fake_request_json,
        )
    exc = caught.value
    assert exc.__cause__ is None
    assert exc.__context__ is None
    rendered = f"{exc!r} {exc} {getattr(exc, '__traceback__', None)}"
    assert "super-secret" not in rendered
    assert "0xdead" not in rendered
    assert "attacker.example" not in str(exc)
    assert "[redacted World ID verification error]" in str(exc)


def test_world_id_verification_result_nullifier_not_in_repr_or_serialization() -> None:
    nullifier = "0xverified-nullifier-secret-value"
    result = WorldIdVerificationResult(
        success=True,
        action=DEFAULT_WORLD_ID_ACTION,
        nullifier=nullifier,
        created_at="2026-06-13T00:00:00Z",
        environment="staging",
        session_id="session-secret-123",
        message="verified",
        results=(
            {
                "identifier": "orb",
                "success": True,
                "nullifier": nullifier,
            },
        ),
        raw_response={"success": True, "nullifier": nullifier},
    )

    # Attribute access remains available for private binding logic.
    assert result.nullifier == nullifier
    assert result.has_nullifier is True

    for surface in (repr(result), str(result), json.dumps(result.public_dict()), json.dumps(result.to_dict())):
        assert nullifier not in surface
        assert "session-secret-123" not in surface
        assert "0xverified" not in surface

    public = result.public_dict()
    assert public["has_nullifier"] is True
    assert "nullifier" not in public
    assert public["has_session_id"] is True
    assert "session_id" not in public
    assert all(item.get("nullifier") == "[redacted]" for item in public["results"])  # type: ignore[union-attr]


def test_normalize_result_surfaces_never_serialize_raw_nullifier(fixtures_dir: Path) -> None:
    success = json.loads((fixtures_dir / "verify_success.json").read_text(encoding="utf-8"))
    ok = normalize_world_id_verification_response(success["raw_response"])
    raw_nullifier = ok.nullifier
    assert raw_nullifier
    assert raw_nullifier not in repr(ok)
    assert raw_nullifier not in str(ok)
    assert raw_nullifier not in json.dumps(ok.public_dict())
    assert raw_nullifier not in json.dumps(ok.to_dict())
