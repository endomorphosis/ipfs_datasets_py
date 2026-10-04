"""Durable World ID wallet bindings and privacy-safe nullifier indexes."""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from ....wallet.models import WorldIdBinding, utc_now


WORLD_ID_NULLIFIER_REF_PREFIX = "worldid-nullifier-ref:v1:"


class WorldIdBindingError(ValueError):
    """Raised when binding state violates authorization or uniqueness rules."""


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _required(value: object, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise WorldIdBindingError(f"{name} is required")
    return normalized


def _unique_strings(values: Iterable[object] | None) -> list[str]:
    result: list[str] = []
    for value in values or ():
        normalized = str(value or "").strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _schema_ids(values: Iterable[object] | None) -> list[int]:
    result: list[int] = []
    for value in values or ():
        if isinstance(value, bool):
            raise WorldIdBindingError("issuer_schema_ids must contain positive integers")
        parsed = int(value)
        if parsed <= 0:
            raise WorldIdBindingError("issuer_schema_ids must contain positive integers")
        if parsed not in result:
            result.append(parsed)
    return result


_PRIVATE_PERSISTENCE_KEYS = {
    "developer_portal_response",
    "idkit_payload",
    "integrity_bundle",
    "jwt",
    "nonce",
    "nullifier",
    "proof",
    "raw_nullifier",
    "responses",
    "rp_signature",
    "session_nullifier",
    "signature",
}


def _persistent_metadata(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key)
            lowered = normalized.lower()
            if lowered in _PRIVATE_PERSISTENCE_KEYS or lowered.endswith("_key"):
                continue
            safe = _persistent_metadata(item)
            if safe is not None:
                result[normalized] = safe
        return result
    if isinstance(value, (list, tuple)):
        return [safe for item in value if (safe := _persistent_metadata(item)) is not None]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return None


def binding_is_active(binding: WorldIdBinding, *, now_min: int | None = None) -> bool:
    """Return whether a binding may back a currently verified receipt."""

    current_minute = int(time.time() // 60) if now_min is None else int(now_min)
    return (
        binding.status == "active"
        and binding.verification_status == "verified"
        and (binding.expires_at_min is None or current_minute < int(binding.expires_at_min))
    )


class WorldIdBindingStore:
    """Thread-safe binding repository with atomic nullifier uniqueness."""

    SNAPSHOT_VERSION = 1

    def __init__(self, *, hmac_key: bytes | None = None) -> None:
        self._hmac_key = bytes(hmac_key) if hmac_key else None
        self._lock = threading.RLock()
        self.bindings: dict[str, WorldIdBinding] = {}
        self.binding_ids_by_wallet: dict[str, list[str]] = {}
        self.binding_ids_by_nullifier: dict[str, str] = {}
        # These keyed commitments are durable. No raw nullifier is retained.
        self.replay_commitments: dict[str, str] = {}

    def register(
        self,
        *,
        wallet_id: str,
        actor_did: str,
        rp_id: str,
        action: str,
        protocol_version: str,
        environment: str,
        nullifier_ref: str | None = None,
        raw_nullifier: str | None = None,
        nullifier_ref_key: bytes | None = None,
        app_id: str = "",
        credential_identifiers: Iterable[object] | None = None,
        issuer_schema_ids: Iterable[object] | None = None,
        proof_receipt_id: str | None = None,
        session_id: str = "",
        signal_hash_ref: str = "",
        verification_status: str = "verified",
        verified_at: str | None = None,
        expires_at_min: int | None = None,
        metadata: Mapping[str, Any] | None = None,
        challenge_id: str = "",
        signal_context: str = "",
        credential_policy: str = "proof_of_human",
        user_presence_verified: bool | None = None,
        provider_context: Mapping[str, Any] | None = None,
    ) -> tuple[WorldIdBinding, bool]:
        """Atomically create a binding, returning ``(binding, created)``."""

        wallet = _required(wallet_id, "wallet_id")
        actor = _required(actor_did, "actor_did")
        relying_party = _required(rp_id, "rp_id")
        selected_action = _required(action, "action")
        protocol = _required(protocol_version, "protocol_version")
        if protocol not in {"3.0", "4.0"}:
            raise WorldIdBindingError("protocol_version must be 3.0 or 4.0")
        selected_environment = _required(environment, "environment").lower()
        if selected_environment not in {"staging", "production"}:
            raise WorldIdBindingError("environment must be staging or production")
        raw = str(raw_nullifier or "").strip()
        replay_commitment = self.nullifier_replay_commitment(
            relying_party, selected_action, selected_environment, raw
        ) if raw else ""
        normalized_ref = str(nullifier_ref or "").strip()
        if raw:
            normalized_ref = self.nullifier_reference(
                wallet,
                relying_party,
                selected_action,
                selected_environment,
                raw,
                key=nullifier_ref_key,
            )
            provided = str(nullifier_ref or "").strip()
            if provided and not hmac.compare_digest(provided, normalized_ref):
                raise WorldIdBindingError("nullifier_ref does not match raw_nullifier commitment")
        else:
            normalized_ref = _required(normalized_ref, "nullifier_ref")
        normalized_expiry: int | None = None
        if expires_at_min is not None:
            if isinstance(expires_at_min, bool) or int(expires_at_min) <= 0:
                raise WorldIdBindingError("expires_at_min must be a positive integer")
            normalized_expiry = int(expires_at_min)
        normalized_provider = json.loads(json.dumps(dict(provider_context or {}), sort_keys=True))

        with self._lock:
            existing_id = (
                self.replay_commitments.get(replay_commitment)
                if replay_commitment
                else self.binding_ids_by_nullifier.get(normalized_ref)
            )
            if existing_id:
                existing = self.bindings[existing_id]
                if (
                    existing.wallet_id == wallet
                    and existing.rp_id == relying_party
                    and existing.action == selected_action
                    and existing.environment == selected_environment
                ):
                    return existing, False
                label = "raw nullifier" if replay_commitment else "nullifier reference"
                raise WorldIdBindingError(f"World ID {label} is already bound")
            existing_ref_id = self.binding_ids_by_nullifier.get(normalized_ref)
            if existing_ref_id:
                existing = self.bindings[existing_ref_id]
                if existing.wallet_id == wallet and existing.rp_id == relying_party and existing.action == selected_action:
                    return existing, False
                raise WorldIdBindingError("World ID nullifier reference is already bound")
            now = utc_now()
            binding = WorldIdBinding(
                binding_id=f"world-id-binding-{uuid.uuid4().hex}",
                wallet_id=wallet,
                actor_did=actor,
                rp_id=relying_party,
                app_id=str(app_id or "").strip(),
                action=selected_action,
                protocol_version=protocol,
                environment=selected_environment,
                nullifier_ref=normalized_ref,
                credential_identifiers=_unique_strings(credential_identifiers),
                issuer_schema_ids=_schema_ids(issuer_schema_ids),
                proof_receipt_id=str(proof_receipt_id or "").strip() or None,
                session_id=str(session_id or "").strip(),
                signal_hash_ref=str(signal_hash_ref or "").strip(),
                verification_status=_required(verification_status, "verification_status"),
                verified_at=str(verified_at or now),
                expires_at_min=normalized_expiry,
                created_at=now,
                updated_at=now,
                metadata=_persistent_metadata(dict(metadata or {})),
                challenge_id=str(challenge_id or "").strip(),
                signal_context=str(signal_context or "").strip(),
                credential_policy=_required(credential_policy, "credential_policy"),
                user_presence_verified=user_presence_verified,
                provider_context=normalized_provider,
            )
            self._store_unlocked(binding)
            if replay_commitment:
                self.replay_commitments[replay_commitment] = binding.binding_id
            return binding, True

    def store(self, binding: WorldIdBinding, *, replay_commitment: str | None = None) -> None:
        with self._lock:
            self._store_unlocked(binding)
            if replay_commitment:
                existing = self.replay_commitments.get(replay_commitment)
                if existing and existing != binding.binding_id:
                    raise WorldIdBindingError("World ID replay commitment is already bound")
                self.replay_commitments[replay_commitment] = binding.binding_id

    def get(self, binding_id: str) -> WorldIdBinding:
        try:
            return self.bindings[binding_id]
        except KeyError as exc:
            raise WorldIdBindingError(f"World ID binding not found: {binding_id}") from exc

    def list_for_wallet(self, wallet_id: str) -> list[WorldIdBinding]:
        return [self.bindings[item] for item in self.binding_ids_by_wallet.get(wallet_id, ())]

    def find_by_nullifier(self, nullifier_ref: str) -> WorldIdBinding | None:
        binding_id = self.binding_ids_by_nullifier.get(str(nullifier_ref or "").strip())
        return self.bindings.get(binding_id) if binding_id else None

    def revoke(self, binding_id: str, *, reason: str = "", now: str | None = None) -> WorldIdBinding:
        with self._lock:
            binding = self.get(binding_id)
            if binding.status != "revoked":
                timestamp = str(now or utc_now())
                binding.status = "revoked"
                binding.revoked_at = timestamp
                binding.updated_at = timestamp
                binding.metadata = {**dict(binding.metadata), "revoked_reason": str(reason or "").strip()}
            return binding

    def active(self, binding_id: str, *, now_min: int | None = None) -> WorldIdBinding:
        binding = self.get(binding_id)
        if not binding_is_active(binding, now_min=now_min):
            raise WorldIdBindingError("World ID binding is revoked, expired, or unverified")
        return binding

    def minimum_projection(
        self,
        binding_id: str,
        *,
        caller_did: str,
        authorize: Callable[[str, WorldIdBinding], bool],
        now_min: int | None = None,
    ) -> dict[str, Any]:
        """Return the minimum useful projection after explicit authorization."""

        caller = _required(caller_did, "caller_did")
        binding = self.active(binding_id, now_min=now_min)
        if not authorize(caller, binding):
            raise WorldIdBindingError("caller is not authorized for the World ID projection")
        return {
            "binding_id": binding.binding_id,
            "wallet_id": binding.wallet_id,
            "status": "active",
            "verification_status": "verified",
            "protocol_version": binding.protocol_version,
            "environment": binding.environment,
            "action": binding.action,
            "credential_policy": binding.credential_policy,
            "credential_identifiers": list(binding.credential_identifiers),
            "expires_at_min": binding.expires_at_min,
        }

    def snapshot(self, *, wallet_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            selected = [
                binding for binding in self.bindings.values()
                if wallet_id is None or binding.wallet_id == wallet_id
            ]
            selected_ids = {binding.binding_id for binding in selected}
            return {
                "version": self.SNAPSHOT_VERSION,
                "bindings": [
                    binding.to_dict() for binding in sorted(selected, key=lambda value: value.binding_id)
                ],
                "replay_commitments": {
                    commitment: binding_id
                    for commitment, binding_id in sorted(self.replay_commitments.items())
                    if binding_id in selected_ids
                },
            }

    def restore(self, snapshot: Mapping[str, Any] | None) -> None:
        if not snapshot:
            return
        items = snapshot.get("bindings", snapshot.get("world_id_bindings", []))
        with self._lock:
            for item in items:
                if isinstance(item, Mapping):
                    self._store_unlocked(WorldIdBinding(**dict(item)))
            for commitment, binding_id in dict(snapshot.get("replay_commitments", {})).items():
                if str(binding_id) in self.bindings:
                    self.replay_commitments[str(commitment)] = str(binding_id)

    def nullifier_replay_commitment(
        self, rp_id: str, action: str, environment: str, raw_nullifier: str
    ) -> str:
        payload = {
            "domain": "world-id-raw-nullifier-replay-v1",
            "rp_id": _required(rp_id, "rp_id"),
            "action": _required(action, "action"),
            "environment": _required(environment, "environment").lower(),
            "raw_nullifier": _required(raw_nullifier, "raw_nullifier"),
        }
        if self._hmac_key:
            return "hmac-sha256:" + hmac.new(
                self._hmac_key, _canonical_bytes(payload), hashlib.sha256
            ).hexdigest()
        return "sha256:" + hashlib.sha256(_canonical_bytes(payload)).hexdigest()

    def nullifier_reference(
        self,
        wallet_id: str,
        rp_id: str,
        action: str,
        environment: str,
        raw_nullifier: str,
        *,
        key: bytes | None = None,
    ) -> str:
        selected_key = bytes(key) if key else self._hmac_key
        if not selected_key:
            raise WorldIdBindingError("a configured HMAC key is required to derive nullifier_ref")
        digest = hmac.new(
            selected_key,
            _canonical_bytes(
                {
                    "domain": "world-id-wallet-nullifier-ref-v1",
                    "wallet_id": _required(wallet_id, "wallet_id"),
                    "rp_id": _required(rp_id, "rp_id"),
                    "action": _required(action, "action"),
                    "environment": _required(environment, "environment").lower(),
                    "raw_nullifier": _required(raw_nullifier, "raw_nullifier"),
                }
            ),
            hashlib.sha256,
        ).hexdigest()
        return f"{WORLD_ID_NULLIFIER_REF_PREFIX}{digest}"

    def _store_unlocked(self, binding: WorldIdBinding) -> None:
        old = self.bindings.get(binding.binding_id)
        if old is not None:
            old_ids = self.binding_ids_by_wallet.get(old.wallet_id, [])
            self.binding_ids_by_wallet[old.wallet_id] = [
                item for item in old_ids if item != binding.binding_id
            ]
            if self.binding_ids_by_nullifier.get(old.nullifier_ref) == binding.binding_id:
                self.binding_ids_by_nullifier.pop(old.nullifier_ref, None)
        conflict = self.binding_ids_by_nullifier.get(binding.nullifier_ref)
        if conflict and conflict != binding.binding_id:
            raise WorldIdBindingError("World ID nullifier reference is already bound")
        self.bindings[binding.binding_id] = binding
        wallet_ids = self.binding_ids_by_wallet.setdefault(binding.wallet_id, [])
        if binding.binding_id not in wallet_ids:
            wallet_ids.append(binding.binding_id)
        self.binding_ids_by_nullifier[binding.nullifier_ref] = binding.binding_id


__all__ = [
    "WORLD_ID_NULLIFIER_REF_PREFIX",
    "WorldIdBinding",
    "WorldIdBindingError",
    "WorldIdBindingStore",
    "binding_is_active",
]
