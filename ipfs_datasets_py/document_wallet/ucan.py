"""Wallet-specific UCAN-style authorization primitives.

This module intentionally exposes a small verifier for wallet grants. It models
resources, abilities, caveats, attenuation, expiry, and revocation while keeping
the wire codec replaceable by a full UCAN implementation later.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Iterable, Optional

from .exceptions import AuthorizationError
from .models import WalletGrant


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    reason: str
    grant_id: Optional[str] = None


def document_resource(wallet_id: str, document_id: str) -> str:
    return f"wallet://{wallet_id}/documents/{document_id}"


def wallet_resource(wallet_id: str) -> str:
    return f"wallet://{wallet_id}"


def _matches(pattern: str, value: str) -> bool:
    if pattern == "*" or pattern == value:
        return True
    if pattern.endswith("*"):
        return value.startswith(pattern[:-1])
    return False


def _time_from_caveat(value: object) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


class GrantRevocationStore:
    """Append-only revocation index for wallet grants."""

    def __init__(self) -> None:
        self._revoked: Dict[str, float] = {}

    def revoke(self, grant_id: str, *, revoked_at: Optional[float] = None) -> None:
        self._revoked[grant_id] = float(revoked_at or time.time())

    def is_revoked(self, grant_id: str) -> bool:
        return grant_id in self._revoked

    def revoked_at(self, grant_id: str) -> Optional[float]:
        return self._revoked.get(grant_id)


class WalletGrantVerifier:
    """Evaluate wallet grants for a principal/resource/ability request."""

    def __init__(self, revocations: Optional[GrantRevocationStore] = None) -> None:
        self.revocations = revocations or GrantRevocationStore()

    def decide(
        self,
        grants: Iterable[WalletGrant],
        *,
        actor_did: str,
        resource: str,
        ability: str,
        now: Optional[float] = None,
        context: Optional[Dict[str, object]] = None,
    ) -> AccessDecision:
        now_value = float(now if now is not None else time.time())
        context = context or {}
        for grant in grants:
            reason = self._grant_denial_reason(
                grant,
                actor_did=actor_did,
                resource=resource,
                ability=ability,
                now=now_value,
                context=context,
            )
            if reason is None:
                return AccessDecision(True, "allowed", grant.grant_id)
        return AccessDecision(False, "no active grant covers this request")

    def require(
        self,
        grants: Iterable[WalletGrant],
        *,
        actor_did: str,
        resource: str,
        ability: str,
        now: Optional[float] = None,
        context: Optional[Dict[str, object]] = None,
    ) -> AccessDecision:
        decision = self.decide(
            grants,
            actor_did=actor_did,
            resource=resource,
            ability=ability,
            now=now,
            context=context,
        )
        if not decision.allowed:
            raise AuthorizationError(decision.reason)
        return decision

    def _grant_denial_reason(
        self,
        grant: WalletGrant,
        *,
        actor_did: str,
        resource: str,
        ability: str,
        now: float,
        context: Dict[str, object],
    ) -> Optional[str]:
        if grant.status != "active":
            return "grant is not active"
        if self.revocations.is_revoked(grant.grant_id):
            return "grant is revoked"
        if grant.audience_did != actor_did:
            return "grant audience does not match actor"
        if grant.expires_at is not None and now > float(grant.expires_at):
            return "grant is expired"
        caveat_expires = _time_from_caveat(grant.caveats.get("expires_at"))
        if caveat_expires is not None and now > caveat_expires:
            return "grant caveat is expired"
        not_before = _time_from_caveat(grant.caveats.get("not_before"))
        if not_before is not None and now < not_before:
            return "grant is not valid yet"
        if not any(_matches(pattern, resource) for pattern in grant.resources):
            return "grant resource does not match"
        if not any(_matches(pattern, ability) for pattern in grant.abilities):
            return "grant ability does not match"
        output_types = grant.caveats.get("output_types")
        requested_output = context.get("output_type")
        if output_types is not None and requested_output is not None:
            if requested_output not in set(output_types):  # type: ignore[arg-type]
                return "requested output type is outside grant caveats"
        return None

