"""IDKit v3/v4 payload parsing, normalization, and proof redaction.

This module is pure: no network I/O.  Public dictionaries and recursive
redaction ensure raw proofs, nullifiers, and integrity material never appear
in logs, errors, or browser-safe projections.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .config import SUPPORTED_WORLD_ID_ENVIRONMENTS, WorldIdConfig


class WorldIdPayloadError(ValueError):
    """Raised when an IDKit proof payload is malformed or unsupported."""


@dataclass(frozen=True)
class WorldIdCredentialResponse:
    """Normalized metadata for one IDKit credential response."""

    identifier: str
    proof_type: str
    signal_hash: str = field(default="", repr=False)
    nullifier: str = field(default="", repr=False)
    session_nullifier: str = field(default="", repr=False)
    session_action: str = field(default="", repr=False)
    issuer_schema_id: int | None = None
    expires_at_min: int | None = None

    @property
    def credential_identifier(self) -> str:
        return self.identifier

    @property
    def nullifier_value(self) -> str:
        return self.session_nullifier or self.nullifier

    def public_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "proof_type": self.proof_type,
            "has_signal_hash": bool(self.signal_hash),
            "has_nullifier": bool(self.nullifier_value),
            "has_session_action": bool(self.session_action),
            "issuer_schema_id": self.issuer_schema_id,
            "expires_at_min": self.expires_at_min,
        }


@dataclass(frozen=True)
class WorldIdIdkitResult:
    """Normalized IDKit result metadata across v3 legacy, v4 uniqueness, and v4 session proofs."""

    protocol_version: str
    nonce: str
    environment: str
    proof_type: str
    responses: tuple[WorldIdCredentialResponse, ...]
    action: str = ""
    action_description: str = ""
    session_id: str = ""
    user_presence_completed: bool | None = None
    identity_attested: bool | None = None
    integrity_bundle_present: bool = False
    raw_response: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @property
    def credential_identifiers(self) -> tuple[str, ...]:
        return tuple(response.identifier for response in self.responses)

    @property
    def signal_hashes(self) -> tuple[str, ...]:
        return tuple(response.signal_hash for response in self.responses if response.signal_hash)

    @property
    def nullifiers(self) -> tuple[str, ...]:
        return tuple(response.nullifier_value for response in self.responses if response.nullifier_value)

    @property
    def session_actions(self) -> tuple[str, ...]:
        return tuple(response.session_action for response in self.responses if response.session_action)

    @property
    def verification_timestamps(self) -> tuple[int, ...]:
        return tuple(
            response.expires_at_min for response in self.responses if response.expires_at_min is not None
        )

    @property
    def expires_at_min_values(self) -> tuple[int, ...]:
        return self.verification_timestamps

    def public_dict(self) -> dict[str, object]:
        return {
            "protocol_version": self.protocol_version,
            "nonce": self.nonce,
            "environment": self.environment,
            "proof_type": self.proof_type,
            "action": self.action,
            "action_description": self.action_description,
            "session_id": self.session_id,
            "user_presence_completed": self.user_presence_completed,
            "identity_attested": self.identity_attested,
            "integrity_bundle_present": self.integrity_bundle_present,
            "credential_identifiers": list(self.credential_identifiers),
            "nullifier_count": len(self.nullifiers),
            "signal_hash_count": len(self.signal_hashes),
            "verification_timestamps": list(self.verification_timestamps),
            "responses": [response.public_dict() for response in self.responses],
        }


def normalize_idkit_response(payload: Mapping[str, Any]) -> WorldIdIdkitResult:
    """Parse the IDKit result shapes returned by World ID 3.0 and 4.0 clients."""

    if not isinstance(payload, Mapping):
        raise WorldIdPayloadError("IDKit response payload must be a JSON object")

    protocol_version = _required_string_field(payload, "protocol_version", "IDKit response")
    if protocol_version not in {"3.0", "4.0"}:
        raise WorldIdPayloadError("IDKit response protocol_version must be 3.0 or 4.0")
    nonce = _required_string_field(payload, "nonce", "IDKit response")
    environment = _required_string_field(payload, "environment", "IDKit response").lower()
    if environment not in SUPPORTED_WORLD_ID_ENVIRONMENTS:
        raise WorldIdPayloadError("IDKit response environment must be staging or production")
    raw_responses = _response_items(payload)
    action_description = _optional_string_field(payload, "action_description", "IDKit response")
    user_presence_completed = _optional_bool_field(payload, "user_presence_completed", "IDKit response")
    identity_attested = _optional_bool_field(payload, "identity_attested", "IDKit response")
    integrity_bundle_present = _integrity_bundle_present(payload)

    if protocol_version == "3.0":
        action = _required_string_field(payload, "action", "IDKit response")
        if _optional_string_field(payload, "session_id", "IDKit response"):
            raise WorldIdPayloadError("IDKit 3.0 responses must not include session_id")
        responses = tuple(_normalize_v3_response(response, index) for index, response in enumerate(raw_responses))
        return WorldIdIdkitResult(
            protocol_version=protocol_version,
            nonce=nonce,
            environment=environment,
            proof_type="legacy",
            action=action,
            action_description=action_description,
            responses=responses,
            user_presence_completed=user_presence_completed,
            identity_attested=identity_attested,
            integrity_bundle_present=integrity_bundle_present,
            raw_response=dict(payload),
        )

    session_id = _optional_string_field(payload, "session_id", "IDKit response")
    has_session_responses = any("session_nullifier" in response for response in raw_responses)
    if session_id or has_session_responses:
        if not session_id:
            raise WorldIdPayloadError("IDKit 4.0 session responses require session_id")
        responses = tuple(
            _normalize_v4_session_response(response, index) for index, response in enumerate(raw_responses)
        )
        return WorldIdIdkitResult(
            protocol_version=protocol_version,
            nonce=nonce,
            environment=environment,
            proof_type="session",
            action=_optional_string_field(payload, "action", "IDKit response"),
            action_description=action_description,
            session_id=session_id,
            responses=responses,
            user_presence_completed=user_presence_completed,
            identity_attested=identity_attested,
            integrity_bundle_present=integrity_bundle_present,
            raw_response=dict(payload),
        )

    action = _required_string_field(payload, "action", "IDKit response")
    responses = tuple(_normalize_v4_response(response, index) for index, response in enumerate(raw_responses))
    return WorldIdIdkitResult(
        protocol_version=protocol_version,
        nonce=nonce,
        environment=environment,
        proof_type="uniqueness",
        action=action,
        action_description=action_description,
        responses=responses,
        user_presence_completed=user_presence_completed,
        identity_attested=identity_attested,
        integrity_bundle_present=integrity_bundle_present,
        raw_response=dict(payload),
    )


def normalize_world_id_idkit_response(payload: Mapping[str, Any]) -> WorldIdIdkitResult:
    """Alias with explicit World ID naming for API callers."""

    return normalize_idkit_response(payload)


def assert_idkit_allowed_by_config(result: WorldIdIdkitResult, config: WorldIdConfig) -> None:
    """Reject normalized IDKit evidence that the config does not permit.

    Safe defaults reject legacy (v3) proofs unless ``allow_legacy_proofs`` is
    explicitly enabled.  Presence requirements are also enforced when configured.
    """

    if result.proof_type == "legacy" and not config.allow_legacy_proofs:
        raise WorldIdPayloadError(
            "legacy IDKit evidence is rejected by default; set WORLD_ID_ALLOW_LEGACY_PROOFS to permit"
        )
    if config.require_user_presence and result.user_presence_completed is not True:
        raise WorldIdPayloadError("IDKit response user_presence_completed is required")
    if config.enabled and result.environment and result.environment != config.environment:
        raise WorldIdPayloadError("IDKit response environment does not match configured environment")
    if result.action and result.action not in config.allowed_actions:
        raise WorldIdPayloadError("IDKit response action is not allowed")


def redact_world_id_payload(value: Any) -> Any:
    """Redact IDKit proof-heavy values before logging or surfacing errors."""

    sensitive_keys = {
        "integrity_bundle",
        "jwt",
        "merkle_root",
        "nullifier",
        "proof",
        "rp_signature",
        "responses",
        "root",
        "raw_response",
        "developer_portal_response",
        "idkit_payload",
        "session_nullifier",
        "signal_hash",
        "signature",
    }
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in sensitive_keys or lowered.endswith("_key"):
                redacted[str(key)] = "[redacted]"
            else:
                redacted[str(key)] = redact_world_id_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_world_id_payload(item) for item in value]
    return value


def _normalize_v3_response(response: Mapping[str, Any], index: int) -> WorldIdCredentialResponse:
    context = f"IDKit response responses[{index}]"
    _required_string_field(response, "proof", context)
    _required_string_field(response, "merkle_root", context)
    return WorldIdCredentialResponse(
        identifier=_required_string_field(response, "identifier", context),
        proof_type="legacy",
        signal_hash=_required_string_field(response, "signal_hash", context),
        nullifier=_required_string_field(response, "nullifier", context),
    )


def _normalize_v4_response(response: Mapping[str, Any], index: int) -> WorldIdCredentialResponse:
    context = f"IDKit response responses[{index}]"
    if "session_nullifier" in response:
        raise WorldIdPayloadError(f"{context} must not include session_nullifier for uniqueness proofs")
    _proof_list(response, context)
    return WorldIdCredentialResponse(
        identifier=_required_string_field(response, "identifier", context),
        proof_type="uniqueness",
        signal_hash=_optional_string_field(response, "signal_hash", context),
        nullifier=_required_string_field(response, "nullifier", context),
        issuer_schema_id=_positive_int_field(response, "issuer_schema_id", context),
        expires_at_min=_positive_int_field(response, "expires_at_min", context),
    )


def _normalize_v4_session_response(response: Mapping[str, Any], index: int) -> WorldIdCredentialResponse:
    context = f"IDKit response responses[{index}]"
    if "nullifier" in response:
        raise WorldIdPayloadError(f"{context} must not include nullifier for session proofs")
    _proof_list(response, context)
    session_nullifier = response.get("session_nullifier")
    if not isinstance(session_nullifier, list) or len(session_nullifier) != 2:
        raise WorldIdPayloadError(f"{context}.session_nullifier must be a two-item list")
    session_values = [
        _non_empty_string(value, f"{context}.session_nullifier[{idx}]")
        for idx, value in enumerate(session_nullifier)
    ]
    return WorldIdCredentialResponse(
        identifier=_required_string_field(response, "identifier", context),
        proof_type="session",
        signal_hash=_optional_string_field(response, "signal_hash", context),
        session_nullifier=session_values[0],
        session_action=session_values[1],
        issuer_schema_id=_positive_int_field(response, "issuer_schema_id", context),
        expires_at_min=_positive_int_field(response, "expires_at_min", context),
    )


def _response_items(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw_responses = payload.get("responses")
    if not isinstance(raw_responses, list) or not raw_responses:
        raise WorldIdPayloadError("IDKit response responses must be a non-empty list")
    responses: list[Mapping[str, Any]] = []
    for index, response in enumerate(raw_responses):
        if not isinstance(response, Mapping):
            raise WorldIdPayloadError(f"IDKit response responses[{index}] must be a JSON object")
        responses.append(response)
    return responses


def _proof_list(response: Mapping[str, Any], context: str) -> list[str]:
    proof = response.get("proof")
    if not isinstance(proof, list) or len(proof) < 5:
        raise WorldIdPayloadError(f"{context}.proof must be a list with at least five proof elements")
    return [_non_empty_string(value, f"{context}.proof[{index}]") for index, value in enumerate(proof)]


def _required_string_field(source: Mapping[str, Any], name: str, context: str) -> str:
    if name not in source:
        raise WorldIdPayloadError(f"{context}.{name} is required")
    return _non_empty_string(source.get(name), f"{context}.{name}")


def _optional_string_field(source: Mapping[str, Any], name: str, context: str) -> str:
    if name not in source or source.get(name) is None:
        return ""
    return _non_empty_string(source.get(name), f"{context}.{name}")


def _non_empty_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorldIdPayloadError(f"{context} must be a non-empty string")
    return value.strip()


def _optional_bool_field(source: Mapping[str, Any], name: str, context: str) -> bool | None:
    if name not in source or source.get(name) is None:
        return None
    value = source.get(name)
    if not isinstance(value, bool):
        raise WorldIdPayloadError(f"{context}.{name} must be a boolean")
    return value


def _positive_int_field(source: Mapping[str, Any], name: str, context: str) -> int:
    if name not in source:
        raise WorldIdPayloadError(f"{context}.{name} is required")
    value = source.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise WorldIdPayloadError(f"{context}.{name} must be a positive integer")
    return value


def _integrity_bundle_present(payload: Mapping[str, Any]) -> bool:
    if "integrity_bundle" not in payload or payload.get("integrity_bundle") is None:
        return False
    if not isinstance(payload.get("integrity_bundle"), Mapping):
        raise WorldIdPayloadError("IDKit response integrity_bundle must be a JSON object")
    return True


__all__ = [
    "WorldIdCredentialResponse",
    "WorldIdIdkitResult",
    "WorldIdPayloadError",
    "assert_idkit_allowed_by_config",
    "normalize_idkit_response",
    "normalize_world_id_idkit_response",
    "redact_world_id_payload",
]
