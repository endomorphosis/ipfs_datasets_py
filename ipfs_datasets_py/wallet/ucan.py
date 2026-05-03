"""Wallet-specific UCAN-style capability checks."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from .exceptions import AccessDeniedError
from .models import Grant


def resource_for_record(wallet_id: str, record_id: str) -> str:
    return f"wallet://{wallet_id}/records/{record_id}"


def resource_for_location(wallet_id: str, record_id: str) -> str:
    return f"wallet://{wallet_id}/location/{record_id}"


def resource_for_wallet(wallet_id: str) -> str:
    return f"wallet://{wallet_id}"


def is_expired(expires_at: str | None, now: datetime | None = None) -> bool:
    if not expires_at:
        return False
    current = now or datetime.now(datetime.fromisoformat(expires_at).tzinfo)
    return current > datetime.fromisoformat(expires_at)


def _matches_resource(grant_resources: Iterable[str], resource: str) -> bool:
    for candidate in grant_resources:
        if candidate == "*" or candidate == resource:
            return True
        if candidate.endswith("/*") and resource.startswith(candidate[:-1]):
            return True
    return False


def assert_grant_allows(grant: Grant, *, audience_did: str, resource: str, ability: str) -> None:
    if grant.status != "active":
        raise AccessDeniedError(f"Grant {grant.grant_id} is not active")
    if grant.audience_did != audience_did:
        raise AccessDeniedError("Grant audience does not match actor")
    if is_expired(grant.expires_at):
        raise AccessDeniedError(f"Grant {grant.grant_id} has expired")
    if ability not in grant.abilities and "*" not in grant.abilities:
        raise AccessDeniedError(f"Grant {grant.grant_id} does not allow {ability}")
    if not _matches_resource(grant.resources, resource):
        raise AccessDeniedError(f"Grant {grant.grant_id} does not cover {resource}")
