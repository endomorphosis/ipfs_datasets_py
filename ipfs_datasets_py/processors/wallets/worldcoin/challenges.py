"""Durable, privacy-safe World ID challenge and replay state.

Only keyed commitments are persisted. Raw nonces and nullifiers are accepted
at the API boundary, compared under a lock, and then discarded.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


class WorldIdChallengeError(ValueError):
    """Raised when challenge evidence is missing, stale, mismatched, or replayed."""


class WorldIdReplayError(WorldIdChallengeError):
    """Raised when a challenge or nullifier commitment was already consumed."""


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _required(value: object, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise WorldIdChallengeError(f"{name} is required")
    return normalized


def _context(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise WorldIdChallengeError("provider_context must be a mapping")
    # JSON normalization makes equality deterministic and rejects opaque values.
    try:
        normalized = json.loads(json.dumps(dict(value), sort_keys=True, separators=(",", ":")))
    except (TypeError, ValueError) as exc:
        raise WorldIdChallengeError("provider_context must contain JSON values") from exc
    if not isinstance(normalized, dict):
        raise WorldIdChallengeError("provider_context must be a mapping")
    return normalized


@dataclass
class WorldIdChallenge:
    """A durable challenge descriptor with no raw nonce material."""

    challenge_id: str
    nonce_commitment: str
    signal_context: str
    action: str
    environment: str
    credential_policy: str
    require_user_presence: bool
    protocol_version: str
    actor_did: str
    provider_context: dict[str, Any] = field(default_factory=dict)
    issued_at: int = 0
    expires_at: int = 0
    status: str = "issued"
    consumed_at: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WorldIdChallengeStore:
    """Thread-safe challenge and replay store backed by snapshot hooks."""

    SNAPSHOT_VERSION = 1

    def __init__(self, hmac_key: bytes, *, now: Callable[[], float] | None = None) -> None:
        key = bytes(hmac_key)
        if not key:
            raise WorldIdChallengeError("a configured HMAC key is required")
        self._hmac_key = key
        self._now = now or time.time
        self._lock = threading.RLock()
        self.challenges: dict[str, WorldIdChallenge] = {}
        self.replay_commitments: dict[str, str] = {}

    def issue(
        self,
        *,
        nonce: str,
        signal: str = "",
        signal_context: str,
        action: str,
        environment: str,
        credential_policy: str,
        require_user_presence: bool,
        protocol_version: str,
        actor_did: str,
        provider_context: Mapping[str, Any] | None = None,
        ttl_seconds: int = 300,
        challenge_id: str | None = None,
        now: int | None = None,
    ) -> WorldIdChallenge:
        if isinstance(ttl_seconds, bool) or int(ttl_seconds) <= 0:
            raise WorldIdChallengeError("ttl_seconds must be a positive integer")
        issued_at = int(self._now() if now is None else now)
        challenge = WorldIdChallenge(
            challenge_id=_required(challenge_id or f"world-id-challenge-{secrets.token_hex(16)}", "challenge_id"),
            nonce_commitment=self._challenge_commitment(
                nonce=nonce,
                signal=signal,
                signal_context=signal_context,
                action=action,
                environment=environment,
                credential_policy=credential_policy,
                require_user_presence=require_user_presence,
                protocol_version=protocol_version,
                actor_did=actor_did,
                provider_context=provider_context,
            ),
            signal_context=_required(signal_context, "signal_context"),
            action=_required(action, "action"),
            environment=_required(environment, "environment").lower(),
            credential_policy=_required(credential_policy, "credential_policy"),
            require_user_presence=bool(require_user_presence),
            protocol_version=_required(protocol_version, "protocol_version"),
            actor_did=_required(actor_did, "actor_did"),
            provider_context=_context(provider_context),
            issued_at=issued_at,
            expires_at=issued_at + int(ttl_seconds),
        )
        with self._lock:
            if challenge.challenge_id in self.challenges:
                raise WorldIdChallengeError("challenge_id already exists")
            self.challenges[challenge.challenge_id] = challenge
        return challenge

    def consume(
        self,
        challenge_id: str,
        *,
        nonce: str,
        signal: str = "",
        signal_context: str,
        action: str,
        environment: str,
        credential_policy: str,
        user_presence_completed: bool | None,
        protocol_version: str,
        actor_did: str,
        provider_context: Mapping[str, Any] | None = None,
        replay_value: str | None = None,
        now: int | None = None,
    ) -> WorldIdChallenge:
        """Atomically validate and consume a challenge and optional replay value."""

        consumed_at = int(self._now() if now is None else now)
        with self._lock:
            challenge = self.challenges.get(_required(challenge_id, "challenge_id"))
            if challenge is None:
                raise WorldIdChallengeError("challenge was not issued")
            if challenge.status == "consumed":
                raise WorldIdReplayError("challenge was already consumed")
            if challenge.status != "issued":
                raise WorldIdChallengeError("challenge is not active")
            if consumed_at >= challenge.expires_at:
                challenge.status = "expired"
                raise WorldIdChallengeError("challenge expired")
            expected = self._challenge_commitment(
                nonce=nonce,
                signal=signal,
                signal_context=signal_context,
                action=action,
                environment=environment,
                credential_policy=credential_policy,
                require_user_presence=challenge.require_user_presence,
                protocol_version=protocol_version,
                actor_did=actor_did,
                provider_context=provider_context,
            )
            if not hmac.compare_digest(challenge.nonce_commitment, expected):
                raise WorldIdChallengeError("challenge context does not match issued challenge")
            if challenge.require_user_presence and user_presence_completed is not True:
                raise WorldIdChallengeError("challenge requires completed user presence")
            replay_commitment = ""
            if replay_value is not None:
                replay_commitment = self.replay_commitment(replay_value)
                if replay_commitment in self.replay_commitments:
                    raise WorldIdReplayError("World ID evidence was already consumed")
            challenge.status = "consumed"
            challenge.consumed_at = consumed_at
            if replay_commitment:
                self.replay_commitments[replay_commitment] = challenge.challenge_id
            return challenge

    def replay_commitment(self, raw_value: str) -> str:
        return self._commit(
            {
                "domain": "world-id-durable-replay-v1",
                "value": _required(raw_value, "replay_value"),
            }
        )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "version": self.SNAPSHOT_VERSION,
                "challenges": [
                    item.to_dict() for item in sorted(self.challenges.values(), key=lambda value: value.challenge_id)
                ],
                "replay_commitments": dict(sorted(self.replay_commitments.items())),
            }

    def restore(self, snapshot: Mapping[str, Any] | None) -> None:
        if not snapshot:
            return
        with self._lock:
            for item in snapshot.get("challenges", []):
                if isinstance(item, Mapping):
                    challenge = WorldIdChallenge(**dict(item))
                    self.challenges[challenge.challenge_id] = challenge
            for commitment, challenge_id in dict(snapshot.get("replay_commitments", {})).items():
                self.replay_commitments[str(commitment)] = str(challenge_id)

    def _challenge_commitment(
        self,
        *,
        nonce: str,
        signal: str,
        signal_context: str,
        action: str,
        environment: str,
        credential_policy: str,
        require_user_presence: bool,
        protocol_version: str,
        actor_did: str,
        provider_context: Mapping[str, Any] | None,
    ) -> str:
        return self._commit(
            {
                "domain": "world-id-issued-challenge-v1",
                "nonce": _required(nonce, "nonce"),
                "signal": str(signal or ""),
                "signal_context": _required(signal_context, "signal_context"),
                "action": _required(action, "action"),
                "environment": _required(environment, "environment").lower(),
                "credential_policy": _required(credential_policy, "credential_policy"),
                "require_user_presence": bool(require_user_presence),
                "protocol_version": _required(protocol_version, "protocol_version"),
                "actor_did": _required(actor_did, "actor_did"),
                "provider_context": _context(provider_context),
            }
        )

    def _commit(self, payload: Mapping[str, Any]) -> str:
        digest = hmac.new(self._hmac_key, _canonical_bytes(payload), hashlib.sha256).hexdigest()
        return f"hmac-sha256:{digest}"


__all__ = [
    "WorldIdChallenge",
    "WorldIdChallengeError",
    "WorldIdChallengeStore",
    "WorldIdReplayError",
]
