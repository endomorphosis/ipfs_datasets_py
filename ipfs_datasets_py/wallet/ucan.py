"""Wallet-specific UCAN-style capability and invocation checks."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime
from typing import Any, Dict, Iterable, Mapping

from .exceptions import AccessDeniedError
from .manifest import canonical_bytes
from .models import Grant, WalletInvocation, utc_now

WALLET_UCAN_TOKEN_PREFIX = "wallet-ucan-v1."
WALLET_UCAN_PROFILE_ID = "wallet-ucan-v1"


def resource_for_record(wallet_id: str, record_id: str) -> str:
    return f"wallet://{wallet_id}/records/{record_id}"


def resource_for_location(wallet_id: str, record_id: str) -> str:
    return f"wallet://{wallet_id}/location/{record_id}"


def resource_for_wallet(wallet_id: str) -> str:
    return f"wallet://{wallet_id}"


def resource_for_export(wallet_id: str) -> str:
    return f"wallet://{wallet_id}/exports"


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


def record_id_from_resource(resource: str) -> str | None:
    """Extract a record id from wallet record/location resources."""

    for marker in ("/records/", "/location/"):
        if marker in resource:
            tail = resource.split(marker, 1)[1]
            record_id = tail.split("/", 1)[0]
            return record_id or None
    return None


def _parse_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
    return datetime.fromisoformat(normalized)


def _caveat_values(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    if isinstance(value, Iterable):
        return {str(item) for item in value}
    return {str(value)}


def _caveat_truthy(caveats: Dict[str, Any], *names: str) -> bool:
    return any(caveats.get(name) is True for name in names)


def assert_caveats_allow(
    caveats: Dict[str, Any],
    *,
    resource: str,
    ability: str,
    invocation_caveats: Dict[str, Any] | None = None,
    record_id: str | None = None,
    data_type: str | None = None,
    now: datetime | None = None,
) -> None:
    """Enforce common wallet UCAN caveats for one capability use."""

    if not caveats:
        return
    invocation_caveats = invocation_caveats or {}
    not_before = caveats.get("not_before") or caveats.get("nbf")
    if not_before:
        valid_after = _parse_datetime(str(not_before))
        current = now or datetime.now(valid_after.tzinfo)
        if current < valid_after:
            raise AccessDeniedError(f"Grant is not valid before {not_before}")

    effective_record_id = record_id or record_id_from_resource(resource)
    allowed_record_ids = caveats.get("record_ids") or caveats.get("allowed_record_ids")
    if allowed_record_ids is not None and effective_record_id is not None:
        if effective_record_id not in _caveat_values(allowed_record_ids):
            raise AccessDeniedError("Grant record_ids caveat does not cover requested record")

    allowed_data_types = caveats.get("data_types") or caveats.get("allowed_data_types")
    if allowed_data_types is not None:
        if data_type is None and effective_record_id is not None:
            raise AccessDeniedError("Grant data_types caveat requires data type context")
        if data_type is not None and data_type not in _caveat_values(allowed_data_types):
            raise AccessDeniedError("Grant data_types caveat does not cover requested data type")

    grant_purpose = caveats.get("purpose")
    invocation_purpose = invocation_caveats.get("purpose")
    if grant_purpose is not None and invocation_purpose is not None and invocation_purpose != grant_purpose:
        raise AccessDeniedError("Invocation purpose does not match grant purpose")

    allowed_outputs = caveats.get("output_types") or caveats.get("allowed_output_types")
    requested_outputs = invocation_caveats.get("output_types") or invocation_caveats.get("output_type")
    if allowed_outputs is not None and requested_outputs is not None:
        if not _caveat_values(requested_outputs).issubset(_caveat_values(allowed_outputs)):
            raise AccessDeniedError("Invocation output_types exceed grant caveat")

    if _caveat_truthy(caveats, "user_presence_required", "require_user_presence"):
        if not _caveat_truthy(invocation_caveats, "user_present", "user_presence"):
            raise AccessDeniedError("Grant requires user presence")


def assert_grant_allows(
    grant: Grant,
    *,
    audience_did: str,
    resource: str,
    ability: str,
    invocation_caveats: Dict[str, Any] | None = None,
    record_id: str | None = None,
    data_type: str | None = None,
) -> None:
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
    assert_caveats_allow(
        grant.caveats,
        resource=resource,
        ability=ability,
        invocation_caveats=invocation_caveats,
        record_id=record_id,
        data_type=data_type,
    )


def create_invocation(
    *,
    grant: Grant,
    audience_did: str,
    resource: str,
    ability: str,
    signing_secret: bytes,
    caveats: Dict[str, Any] | None = None,
    expires_at: str | None = None,
    record_id: str | None = None,
    data_type: str | None = None,
) -> WalletInvocation:
    """Create a signed local UCAN-style invocation for one grant capability."""

    assert_grant_allows(
        grant,
        audience_did=audience_did,
        resource=resource,
        ability=ability,
        invocation_caveats=caveats,
        record_id=record_id,
        data_type=data_type,
    )
    invocation = WalletInvocation(
        invocation_id=f"invocation-{uuid.uuid4().hex}",
        grant_id=grant.grant_id,
        issuer_did=grant.issuer_did,
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
    if data.get("issuer_did") is None:
        data.pop("issuer_did", None)
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
    record_id: str | None = None,
    data_type: str | None = None,
) -> None:
    if invocation.audience_did != audience_did:
        raise AccessDeniedError("Invocation audience does not match actor")
    if invocation.grant_id != grant.grant_id:
        raise AccessDeniedError("Invocation grant does not match")
    if invocation.resource != resource or invocation.ability != ability:
        raise AccessDeniedError("Invocation capability does not match requested action")
    if is_expired(invocation.expires_at):
        raise AccessDeniedError(f"Invocation {invocation.invocation_id} has expired")
    assert_grant_allows(
        grant,
        audience_did=audience_did,
        resource=resource,
        ability=ability,
        invocation_caveats=invocation.caveats,
        record_id=record_id,
        data_type=data_type,
    )
    assert_invocation_signature(invocation, signing_secret)


def invocation_to_token(invocation: WalletInvocation) -> str:
    encoded = base64.urlsafe_b64encode(canonical_bytes(invocation.to_dict())).decode("ascii")
    return f"{WALLET_UCAN_TOKEN_PREFIX}{encoded}"


def invocation_from_token(token: str) -> WalletInvocation:
    if not token.startswith(WALLET_UCAN_TOKEN_PREFIX):
        raise ValueError("Unsupported wallet invocation token")
    payload = base64.urlsafe_b64decode(token[len(WALLET_UCAN_TOKEN_PREFIX) :].encode("ascii"))
    return WalletInvocation(**json.loads(payload.decode("utf-8")))


def wallet_ucan_profile() -> Dict[str, Any]:
    """Return the stable wallet UCAN profile used by wallet invocation tokens."""

    return {
        "profile": WALLET_UCAN_PROFILE_ID,
        "token_prefix": WALLET_UCAN_TOKEN_PREFIX.rstrip("."),
        "encoding": "base64url(canonical-json(WalletInvocation))",
        "signature": "hmac-sha256 over canonical invocation payload with signature removed",
        "resource_scheme": "wallet://",
        "required_invocation_fields": [
            "invocation_id",
            "grant_id",
            "issuer_did",
            "audience_did",
            "resource",
            "ability",
            "caveats",
            "issued_at",
            "nonce",
            "signature",
        ],
        "optional_invocation_fields": ["expires_at"],
        "caveats": [
            "not_before",
            "nbf",
            "record_ids",
            "allowed_record_ids",
            "data_types",
            "allowed_data_types",
            "purpose",
            "output_types",
            "allowed_output_types",
            "user_presence_required",
            "require_user_presence",
            "user_present",
            "user_presence",
            "max_delegation_depth",
        ],
    }


def invocation_to_ucan_profile_payload(
    invocation: WalletInvocation,
    *,
    grant: Grant | Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Map a wallet invocation into a UCAN-compatible inspection payload.

    This is a deterministic compatibility envelope for integrators. It does not
    claim byte-for-byte `ucanto` token encoding; it exposes the fields that a
    UCAN verifier or bridge must preserve.
    """

    grant_dict = grant.to_dict() if isinstance(grant, Grant) else dict(grant or {})
    issuer_did = invocation.issuer_did or grant_dict.get("issuer_did")
    if not issuer_did:
        raise ValueError("issuer_did is required for UCAN profile payload export")
    capability = {
        "with": invocation.resource,
        "can": invocation.ability,
        "nb": dict(invocation.caveats or {}),
    }
    payload = {
        "profile": WALLET_UCAN_PROFILE_ID,
        "ucan": {
            "iss": issuer_did,
            "aud": invocation.audience_did,
            "att": [capability],
            "nnc": invocation.nonce,
            "fct": invocation.issued_at,
            "sig": invocation.signature,
            "prf": [invocation.grant_id],
        },
        "wallet_invocation": invocation.to_dict(),
        "wallet_grant": grant_dict or None,
    }
    if invocation.expires_at:
        payload["ucan"]["exp"] = invocation.expires_at
    return payload
