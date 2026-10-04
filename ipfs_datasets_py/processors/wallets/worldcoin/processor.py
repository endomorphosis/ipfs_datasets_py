"""World ID verification orchestration over pure protocol and durable state."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ....wallet.models import ProofReceipt, WorldIdBinding
from .bindings import WorldIdBindingError, WorldIdBindingStore
from .challenges import WorldIdChallenge, WorldIdChallengeStore
from .config import WorldIdConfig
from .developer_portal import (
    WorldIdRequestJson,
    WorldIdVerificationError,
    WorldIdVerificationResult,
    verify_world_id_proof_from_config,
)
from .idkit import (
    WorldIdIdkitResult,
    assert_idkit_allowed_by_config,
    normalize_world_id_idkit_response,
    redact_world_id_payload,
)
from .proofs import create_world_id_proof_receipt
from .snapshots import export_world_id_state, import_world_id_state


@dataclass(frozen=True)
class WorldIdBindingResult:
    binding: WorldIdBinding
    proof: ProofReceipt
    verification: WorldIdVerificationResult

    def public_dict(self) -> dict[str, Any]:
        return {
            "binding": self.binding.to_dict(),
            "proof": self.proof.to_dict(),
            "verification": redact_world_id_payload(self.verification.public_dict()),
        }


class WorldIdProcessor:
    """Own issued challenges, replay state, bindings, and proof receipts."""

    def __init__(
        self,
        config: WorldIdConfig,
        *,
        hmac_key: bytes | str | None = None,
        request_json: WorldIdRequestJson | None = None,
    ) -> None:
        selected_key = hmac_key
        if selected_key is None:
            selected_key = config.nullifier_hmac_key.value
        if isinstance(selected_key, str):
            selected_key = selected_key.encode("utf-8")
        if not selected_key:
            raise WorldIdBindingError(
                "a resolved WORLD_ID_NULLIFIER_HMAC_KEY is required for durable state"
            )
        self.config = config
        self.request_json = request_json
        self.bindings = WorldIdBindingStore(hmac_key=selected_key)
        self.challenges = WorldIdChallengeStore(selected_key)
        self.proofs: dict[str, ProofReceipt] = {}
        self._lock = threading.RLock()

    def issue_challenge(
        self,
        *,
        nonce: str,
        signal: str = "",
        signal_context: str,
        actor_did: str,
        provider_context: Mapping[str, Any] | None = None,
        action: str | None = None,
        protocol_version: str = "4.0",
        ttl_seconds: int = 300,
        now: int | None = None,
    ) -> WorldIdChallenge:
        selected_action = str(action or self.config.default_action).strip()
        if selected_action not in self.config.allowed_actions:
            raise WorldIdBindingError("World ID action is not allowed")
        return self.challenges.issue(
            nonce=nonce,
            signal=signal,
            signal_context=signal_context,
            action=selected_action,
            environment=self.config.environment,
            credential_policy=self.config.credential_policy,
            require_user_presence=self.config.require_user_presence,
            protocol_version=protocol_version,
            actor_did=actor_did,
            provider_context=provider_context,
            ttl_seconds=ttl_seconds,
            now=now,
        )

    def verify_and_bind(
        self,
        wallet_id: str,
        *,
        actor_did: str,
        challenge_id: str,
        signal: str = "",
        signal_context: str,
        provider_context: Mapping[str, Any] | None,
        idkit_payload: Mapping[str, Any],
        request_json: WorldIdRequestJson | None = None,
        now: int | None = None,
    ) -> WorldIdBindingResult:
        """Verify, consume replay state, create a binding, and issue its receipt."""

        normalized = normalize_world_id_idkit_response(idkit_payload)
        assert_idkit_allowed_by_config(normalized, self.config)
        action = normalized.action or self.config.default_action
        verification = verify_world_id_proof_from_config(
            self.config,
            idkit_payload,
            request_json=request_json or self.request_json,
        )
        self._assert_verification_matches(normalized, verification, action)
        raw_nullifier = verification.nullifier or (
            normalized.nullifiers[0] if normalized.nullifiers else ""
        )
        if not raw_nullifier:
            raise WorldIdVerificationError("World ID verification did not return a nullifier")
        if normalized.nullifiers and raw_nullifier not in normalized.nullifiers:
            raise WorldIdVerificationError("verified nullifier does not match IDKit evidence")
        with self._lock:
            self.challenges.consume(
                challenge_id,
                nonce=normalized.nonce,
                signal=signal,
                signal_context=signal_context,
                action=action,
                environment=normalized.environment,
                credential_policy=self.config.credential_policy,
                user_presence_completed=normalized.user_presence_completed,
                protocol_version=normalized.protocol_version,
                actor_did=actor_did,
                provider_context=provider_context,
                replay_value=raw_nullifier,
                now=now,
            )
            signal_hash_ref = self._signal_hash_ref(normalized)
            binding, _ = self.bindings.register(
                wallet_id=wallet_id,
                actor_did=actor_did,
                rp_id=self.config.rp_id,
                app_id=self.config.app_id,
                action=action,
                protocol_version=normalized.protocol_version,
                environment=normalized.environment,
                raw_nullifier=raw_nullifier,
                credential_identifiers=normalized.credential_identifiers,
                issuer_schema_ids=[
                    response.issuer_schema_id
                    for response in normalized.responses
                    if response.issuer_schema_id is not None
                ],
                session_id=normalized.session_id or verification.session_id,
                signal_hash_ref=signal_hash_ref,
                verification_status="verified",
                verified_at=verification.created_at or None,
                expires_at_min=(
                    min(normalized.expires_at_min_values)
                    if normalized.expires_at_min_values
                    else None
                ),
                metadata={
                    "credential_policy": self.config.credential_policy,
                    "idkit": self._durable_idkit_metadata(normalized),
                    "verification": redact_world_id_payload(verification.public_dict()),
                },
                challenge_id=challenge_id,
                signal_context=signal_context,
                credential_policy=self.config.credential_policy,
                user_presence_verified=normalized.user_presence_completed,
                provider_context=provider_context,
            )
            proof = create_world_id_proof_receipt(binding, now_min=(now // 60 if now else None))
            self.proofs[proof.proof_id] = proof
            binding.proof_receipt_id = proof.proof_id
            return WorldIdBindingResult(binding=binding, proof=proof, verification=verification)

    def revoke(self, binding_id: str, *, reason: str = "") -> WorldIdBinding:
        with self._lock:
            binding = self.bindings.revoke(binding_id, reason=reason)
            if binding.proof_receipt_id and binding.proof_receipt_id in self.proofs:
                self.proofs[binding.proof_receipt_id].verification_status = "revoked"
            return binding

    def minimum_projection(
        self,
        binding_id: str,
        *,
        caller_did: str,
        authorize: Callable[[str, WorldIdBinding], bool],
        now_min: int | None = None,
    ) -> dict[str, Any]:
        return self.bindings.minimum_projection(
            binding_id,
            caller_did=caller_did,
            authorize=authorize,
            now_min=now_min,
        )

    def snapshot(self, *, wallet_id: str | None = None) -> dict[str, Any]:
        return {
            "world_id_state": export_world_id_state(
                self.bindings,
                wallet_id=wallet_id,
                challenges=self.challenges,
                proofs=self.proofs,
            )
        }

    def restore(self, snapshot: Mapping[str, Any]) -> None:
        import_world_id_state(
            snapshot,
            self.bindings,
            challenges=self.challenges,
            proofs=self.proofs,
        )

    @staticmethod
    def _signal_hash_ref(normalized: WorldIdIdkitResult) -> str:
        if not normalized.signal_hashes:
            return ""
        digest = hashlib.sha256(
            json.dumps(sorted(normalized.signal_hashes), separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return f"worldid-signal-ref:v1:{digest}"

    @staticmethod
    def _durable_idkit_metadata(normalized: WorldIdIdkitResult) -> dict[str, Any]:
        metadata = dict(normalized.public_dict())
        metadata.pop("nonce", None)
        metadata["challenge_bound"] = True
        return metadata

    def _assert_verification_matches(
        self,
        normalized: WorldIdIdkitResult,
        verification: WorldIdVerificationResult,
        action: str,
    ) -> None:
        if not verification.success:
            raise WorldIdVerificationError(verification.message or "World ID verification failed")
        if action not in self.config.allowed_actions:
            raise WorldIdVerificationError("World ID action is not allowed")
        if verification.action and verification.action != action:
            raise WorldIdVerificationError("verification action does not match IDKit evidence")
        if normalized.environment != self.config.environment:
            raise WorldIdVerificationError("IDKit environment does not match configured environment")
        if verification.environment and verification.environment != normalized.environment:
            raise WorldIdVerificationError("verification environment does not match IDKit evidence")


__all__ = ["WorldIdBindingResult", "WorldIdProcessor"]
