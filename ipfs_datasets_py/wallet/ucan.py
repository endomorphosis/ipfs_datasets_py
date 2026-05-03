"""Wallet-specific UCAN-style capability and invocation checks."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime
from typing import Any, Dict, Iterable

from .exceptions import AccessDeniedError
from .manifest import canonical_bytes
from .models import Grant, WalletInvocation, utc_now


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


def create_invocation(
    *,
    grant: Grant,
    audience_did: str,
    resource: str,
    ability: str,
    signing_secret: bytes,
    caveats: Dict[str, Any] | None = None,
    expires_at: str | None = None,
) -> WalletInvocation:
    """Create a signed local UCAN-style invocation for one grant capability."""

    assert_grant_allows(grant, audience_did=audience_did, resource=resource, ability=ability)
    invocation = WalletInvocation(
        invocation_id=f"invocation-{uuid.uuid4().hex}",
        grant_id=grant.grant_id,
        audience_did=audience_did,
        resource=resource,
        ability=ability,
        caveats=dict(caveats or {}),
        expires_at=expires_at,
        nonce=f"nonce-{uuid.uuid4().hex}",
    )
    invocation.signature = sign_invocation(invocation, signing_secret)
    return invocation


def invocation_signing_payload(invocation: WalletInvocation) -> Dict[str, Any]:
    """Return the stable payload covered by an invocation signature."""

    data = invocation.to_dict()
    data.pop("signature", None)
    return data


def sign_invocation(invocation: WalletInvocation, signing_secret: bytes) -> str:
    digest = hmac.new(signing_secret, canonical_bytes(invocation_signing_payload(invocation)), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii")


def assert_invocation_signature(invocation: WalletInvocation, signing_secret: bytes) -> None:
    expected = sign_invocation(invocation, signing_secret)
    if not hmac.compare_digest(expected, invocation.signature):
        raise AccessDeniedError(f"Invocation {invocation.invocation_id} signature is invalid")


def assert_invocation_allows(
    invocation: WalletInvocation,
    grant: Grant,
    *,
    audience_did: str,
    resource: str,
    ability: str,
    signing_secret: bytes,
) -> None:
    if invocation.audience_did != audience_did:
        raise AccessDeniedError("Invocation audience does not match actor")
    if invocation.grant_id != grant.grant_id:
        raise AccessDeniedError("Invocation grant does not match")
    if invocation.resource != resource or invocation.ability != ability:
        raise AccessDeniedError("Invocation capability does not match requested action")
    if is_expired(invocation.expires_at):
        raise AccessDeniedError(f"Invocation {invocation.invocation_id} has expired")
    assert_grant_allows(grant, audience_did=audience_did, resource=resource, ability=ability)
    assert_invocation_signature(invocation, signing_secret)


def invocation_to_token(invocation: WalletInvocation) -> str:
    encoded = base64.urlsafe_b64encode(canonical_bytes(invocation.to_dict())).decode("ascii")
    return f"wallet-ucan-v1.{encoded}"


def invocation_from_token(token: str) -> WalletInvocation:
    prefix = "wallet-ucan-v1."
    if not token.startswith(prefix):
        raise ValueError("Unsupported wallet invocation token")
    payload = base64.urlsafe_b64decode(token[len(prefix) :].encode("ascii"))
    return WalletInvocation(**json.loads(payload.decode("utf-8")))
