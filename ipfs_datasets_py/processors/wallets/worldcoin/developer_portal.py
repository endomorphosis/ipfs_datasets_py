"""World Developer Portal verification client and response normalization.

Transport is injected via ``request_json`` so unit tests never open sockets.
The default transport uses stdlib urllib only when explicitly invoked.  Endpoint
policy is bounded: absolute http(s) base URL, finite timeout, and safe error
messages that never echo proof/nullifier material.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request
from urllib.parse import urlparse

from .config import (
    DEFAULT_WORLD_ID_HTTP_TIMEOUT_SECONDS,
    DEFAULT_WORLD_ID_VERIFY_BASE_URL,
    WorldIdConfig,
)
from .idkit import redact_world_id_payload


class WorldIdVerificationError(RuntimeError):
    """Raised when Developer Portal proof verification fails operationally."""


WorldIdRequestJson = Callable[
    [str, str, Mapping[str, Any], Mapping[str, str], float],
    Mapping[str, Any],
]


@dataclass(frozen=True)
class WorldIdVerificationResult:
    """Normalized response from World Developer Portal verification."""

    success: bool
    action: str = ""
    nullifier: str = ""
    created_at: str = ""
    environment: str = ""
    session_id: str = ""
    message: str = ""
    results: tuple[Mapping[str, Any], ...] = ()
    raw_response: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @property
    def successful_results(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(result for result in self.results if bool(result.get("success")))

    def public_dict(self) -> dict[str, object]:
        """Return a browser/log-safe view without raw nullifier material."""

        return {
            "success": self.success,
            "action": self.action,
            "has_nullifier": bool(self.nullifier),
            "created_at": self.created_at,
            "environment": self.environment,
            "session_id": self.session_id,
            "message": self.message,
            "results": [redact_world_id_payload(dict(result)) for result in self.results],
        }


def verify_world_id_proof(
    rp_id: str,
    idkit_payload: Mapping[str, Any],
    *,
    verify_base_url: str = DEFAULT_WORLD_ID_VERIFY_BASE_URL,
    timeout_seconds: float = DEFAULT_WORLD_ID_HTTP_TIMEOUT_SECONDS,
    request_json: WorldIdRequestJson | None = None,
) -> WorldIdVerificationResult:
    """Verify an IDKit result with the World Developer Portal."""

    resolved_rp_id = str(rp_id or "").strip()
    if not resolved_rp_id:
        raise WorldIdVerificationError("rp_id is required")
    base_url = _validate_base_url(verify_base_url)
    timeout = float(timeout_seconds)
    if timeout <= 0:
        raise WorldIdVerificationError("timeout_seconds must be positive")
    url = f"{base_url}/api/v4/verify/{urllib_parse.quote(resolved_rp_id, safe='')}"
    requester = request_json or _default_world_id_request_json
    try:
        response = requester(
            "POST",
            url,
            idkit_payload,
            {"content-type": "application/json"},
            timeout,
        )
    except WorldIdVerificationError:
        raise
    except Exception as exc:
        raise WorldIdVerificationError(
            f"World ID verification request failed: {_safe_error_message(exc)}"
        ) from exc
    return normalize_world_id_verification_response(response, idkit_payload=idkit_payload)


def verify_world_id_proof_from_config(
    config: WorldIdConfig,
    idkit_payload: Mapping[str, Any],
    *,
    request_json: WorldIdRequestJson | None = None,
) -> WorldIdVerificationResult:
    """Verify an IDKit result using a validated World ID config."""

    if not config.enabled:
        raise WorldIdVerificationError("World ID is disabled")
    return verify_world_id_proof(
        config.rp_id,
        idkit_payload,
        verify_base_url=config.verify_base_url,
        timeout_seconds=config.http_timeout_seconds,
        request_json=request_json,
    )


def normalize_world_id_verification_response(
    response: Mapping[str, Any],
    *,
    idkit_payload: Mapping[str, Any] | None = None,
) -> WorldIdVerificationResult:
    """Normalize a Developer Portal verification response."""

    if not isinstance(response, Mapping):
        raise WorldIdVerificationError("World ID verification response must be a JSON object")
    raw_results = response.get("results")
    if raw_results is None:
        raw_results = []
    if not isinstance(raw_results, list):
        raise WorldIdVerificationError("World ID verification response results must be a list")
    results = tuple(result for result in raw_results if isinstance(result, Mapping))
    payload = idkit_payload or {}
    nullifier = str(response.get("nullifier") or "")
    if not nullifier:
        nullifier = next(
            (str(result.get("nullifier") or "") for result in results if result.get("nullifier")),
            "",
        )
    return WorldIdVerificationResult(
        success=bool(response.get("success")),
        action=str(response.get("action") or payload.get("action") or ""),
        nullifier=nullifier,
        created_at=str(response.get("created_at") or ""),
        environment=str(response.get("environment") or payload.get("environment") or ""),
        session_id=str(response.get("session_id") or ""),
        message=str(response.get("message") or ""),
        results=results,
        raw_response=dict(response),
    )


def _validate_base_url(value: str) -> str:
    normalized = str(value or "").strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise WorldIdVerificationError("base URL must be an absolute http(s) URL")
    # Block obvious local/link-local targets from becoming default verification hosts.
    host = (parsed.hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} or host.endswith(".local"):
        raise WorldIdVerificationError("base URL host is not allowed for World ID verification")
    return normalized


def _default_world_id_request_json(
    method: str,
    url: str,
    payload: Mapping[str, Any],
    headers: Mapping[str, str],
    timeout_seconds: float,
) -> Mapping[str, Any]:
    request_body = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        url,
        data=request_body,
        headers=dict(headers),
        method=method,
    )
    try:
        with urllib_request.urlopen(req, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except urllib_error.HTTPError as exc:
        raw_error = exc.read().decode("utf-8", errors="replace")
        raise WorldIdVerificationError(
            f"World ID verification request failed with status {exc.code}: {_redact_text(raw_error)}"
        ) from exc
    try:
        parsed = json.loads(raw or "{}")
    except Exception as exc:
        raise WorldIdVerificationError("World ID verification response was not valid JSON") from exc
    if not isinstance(parsed, Mapping):
        raise WorldIdVerificationError("World ID verification response must be a JSON object")
    return parsed


def _safe_error_message(exc: Exception) -> str:
    return _redact_text(str(exc))


def _redact_text(value: str, *, limit: int = 500) -> str:
    text = str(value or "")
    for marker in ("proof", "nullifier", "session_nullifier", "merkle_root", "signal_hash", "jwt"):
        if marker in text.lower():
            return "[redacted World ID verification error]"
    return text[:limit]


__all__ = [
    "WorldIdRequestJson",
    "WorldIdVerificationError",
    "WorldIdVerificationResult",
    "normalize_world_id_verification_response",
    "verify_world_id_proof",
    "verify_world_id_proof_from_config",
]
