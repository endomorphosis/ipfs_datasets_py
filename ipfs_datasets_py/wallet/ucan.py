"""Wallet-specific UCAN-style capability and invocation checks."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import struct
import uuid
from datetime import datetime
from typing import Any, Dict, Iterable, Mapping

from .exceptions import AccessDeniedError
from .manifest import canonical_bytes
from .models import Grant, WalletInvocation, utc_now

WALLET_UCAN_TOKEN_PREFIX = "wallet-ucan-v1."
WALLET_UCAN_PROFILE_ID = "wallet-ucan-v1"
WALLET_UCAN_CONFORMANCE_FIXTURE_ID = "wallet-ucan-conformance-v1"
WALLET_UCAN_EXTERNAL_ADAPTER_ID = "wallet-ucan-v1-ucanto-w3up-dag-cbor-v1"
WALLET_UCAN_EXTERNAL_ADAPTER_KEY = "ucanto_w3up"
WALLET_UCAN_EXTERNAL_STACK_ID = "ucanto/w3up"
WALLET_UCAN_EXTERNAL_BLOCK_CODEC = "dag-cbor"


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
    if invocation.issuer_did is not None and invocation.issuer_did != grant.issuer_did:
        raise AccessDeniedError("Invocation issuer does not match grant")
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


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def _base64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))


def _cbor_length(major: int, length: int) -> bytes:
    if length < 0:
        raise ValueError("DAG-CBOR length cannot be negative")
    prefix = major << 5
    if length < 24:
        return bytes([prefix | length])
    if length < 256:
        return bytes([prefix | 24, length])
    if length < 65536:
        return bytes([prefix | 25, *length.to_bytes(2, "big")])
    if length < 4294967296:
        return bytes([prefix | 26, *length.to_bytes(4, "big")])
    if length < 18446744073709551616:
        return bytes([prefix | 27, *length.to_bytes(8, "big")])
    raise ValueError("DAG-CBOR length is too large")


def _fallback_dag_cbor_encode(value: Any) -> bytes:
    if value is None:
        return b"\xf6"
    if value is False:
        return b"\xf4"
    if value is True:
        return b"\xf5"
    if isinstance(value, int):
        if value >= 0:
            return _cbor_length(0, value)
        return _cbor_length(1, -1 - value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("DAG-CBOR floats must be finite")
        return b"\xfb" + struct.pack(">d", value)
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        return _cbor_length(3, len(encoded)) + encoded
    if isinstance(value, (list, tuple)):
        return _cbor_length(4, len(value)) + b"".join(_fallback_dag_cbor_encode(item) for item in value)
    if isinstance(value, Mapping):
        encoded_items: list[tuple[bytes, bytes]] = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("DAG-CBOR map keys must be strings")
            encoded_items.append((_fallback_dag_cbor_encode(key), _fallback_dag_cbor_encode(item)))
        encoded_items.sort(key=lambda item: item[0])
        return _cbor_length(5, len(encoded_items)) + b"".join(key + item for key, item in encoded_items)
    raise ValueError(f"Unsupported DAG-CBOR value type: {type(value).__name__}")


def _read_cbor_length(data: bytes, offset: int, additional: int) -> tuple[int, int]:
    if additional < 24:
        return additional, offset
    if additional == 24:
        return data[offset], offset + 1
    if additional == 25:
        return int.from_bytes(data[offset : offset + 2], "big"), offset + 2
    if additional == 26:
        return int.from_bytes(data[offset : offset + 4], "big"), offset + 4
    if additional == 27:
        return int.from_bytes(data[offset : offset + 8], "big"), offset + 8
    raise ValueError("Unsupported DAG-CBOR indefinite or reserved length")


def _fallback_dag_cbor_decode_value(data: bytes, offset: int = 0) -> tuple[Any, int]:
    if offset >= len(data):
        raise ValueError("Unexpected end of DAG-CBOR block")
    initial = data[offset]
    offset += 1
    major = initial >> 5
    additional = initial & 0x1F

    if major == 0:
        return _read_cbor_length(data, offset, additional)
    if major == 1:
        value, offset = _read_cbor_length(data, offset, additional)
        return -1 - value, offset
    if major in {2, 3}:
        length, offset = _read_cbor_length(data, offset, additional)
        raw = data[offset : offset + length]
        if len(raw) != length:
            raise ValueError("Unexpected end of DAG-CBOR byte/string value")
        offset += length
        if major == 2:
            return raw, offset
        return raw.decode("utf-8"), offset
    if major == 4:
        length, offset = _read_cbor_length(data, offset, additional)
        values = []
        for _ in range(length):
            item, offset = _fallback_dag_cbor_decode_value(data, offset)
            values.append(item)
        return values, offset
    if major == 5:
        length, offset = _read_cbor_length(data, offset, additional)
        result: Dict[str, Any] = {}
        for _ in range(length):
            key, offset = _fallback_dag_cbor_decode_value(data, offset)
            if not isinstance(key, str):
                raise ValueError("DAG-CBOR map keys must be strings")
            if key in result:
                raise ValueError("DAG-CBOR map keys must be unique")
            result[key], offset = _fallback_dag_cbor_decode_value(data, offset)
        return result, offset
    if major == 7:
        if additional == 20:
            return False, offset
        if additional == 21:
            return True, offset
        if additional == 22:
            return None, offset
        if additional == 27:
            raw = data[offset : offset + 8]
            if len(raw) != 8:
                raise ValueError("Unexpected end of DAG-CBOR float value")
            return struct.unpack(">d", raw)[0], offset + 8
    raise ValueError("Unsupported DAG-CBOR value")


def _fallback_dag_cbor_decode(data: bytes) -> Dict[str, Any]:
    decoded, offset = _fallback_dag_cbor_decode_value(data)
    if offset != len(data):
        raise ValueError("DAG-CBOR block contains trailing bytes")
    if not isinstance(decoded, Mapping):
        raise ValueError("External UCAN adapter block must decode to a mapping")
    return dict(decoded)


def _dag_cbor_encode(value: Mapping[str, Any]) -> bytes:
    try:
        import dag_cbor  # type: ignore[import]
    except Exception:  # pragma: no cover - dependency is declared for the package.
        return _fallback_dag_cbor_encode(value)
    return dag_cbor.encode(dict(value))


def _dag_cbor_decode(value: bytes) -> Dict[str, Any]:
    try:
        import dag_cbor  # type: ignore[import]
    except Exception:  # pragma: no cover - dependency is declared for the package.
        return _fallback_dag_cbor_decode(value)
    decoded = dag_cbor.decode(value)
    if not isinstance(decoded, Mapping):
        raise ValueError("External UCAN adapter block must decode to a mapping")
    return dict(decoded)


def _unsigned_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("varint value cannot be negative")
    encoded = bytearray()
    while value >= 0x80:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _dag_cbor_cid(value: bytes) -> str:
    try:
        from multiformats import CID, multihash  # type: ignore[import]
    except Exception:  # pragma: no cover - dependency is declared for the package.
        digest = hashlib.sha256(value).digest()
        cid_bytes = (
            _unsigned_varint(1)
            + _unsigned_varint(0x71)
            + _unsigned_varint(0x12)
            + _unsigned_varint(len(digest))
            + digest
        )
        return "b" + base64.b32encode(cid_bytes).decode("ascii").lower().rstrip("=")
    return str(CID("base32", 1, WALLET_UCAN_EXTERNAL_BLOCK_CODEC, multihash.digest(value, "sha2-256")))


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
        "external_adapters": [wallet_ucan_external_adapter_profile()],
    }


def wallet_ucan_external_adapter_profile() -> Dict[str, Any]:
    """Return the target-specific external UCAN adapter contract."""

    return {
        "adapter": WALLET_UCAN_EXTERNAL_ADAPTER_ID,
        "target_stack": WALLET_UCAN_EXTERNAL_STACK_ID,
        "source_profile": WALLET_UCAN_PROFILE_ID,
        "codec": WALLET_UCAN_EXTERNAL_BLOCK_CODEC,
        "cid": "cidv1 base32 dag-cbor sha2-256 over adapter block bytes",
        "role": "adapter conformance only; wallet-ucan-v1 remains the production token",
        "preserved_fields": [
            "iss",
            "aud",
            "att[0].with",
            "att[0].can",
            "att[0].nb",
            "nnc",
            "fct",
            "exp",
            "prf",
            "sig",
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


def _external_ucan_block_from_profile_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    normalized = validate_ucan_profile_payload(payload)
    block = {
        "iss": normalized["issuer_did"],
        "aud": normalized["audience_did"],
        "att": [
            {
                "with": normalized["resource"],
                "can": normalized["ability"],
                "nb": dict(normalized["caveats"]),
            }
        ],
        "nnc": normalized["nonce"],
        "fct": normalized["issued_at"],
        "sig": normalized["signature"],
        "prf": list(normalized["proofs"]),
    }
    if normalized["expires_at"] is not None:
        block["exp"] = normalized["expires_at"]
    return block


def wallet_ucan_external_adapter_fixture(
    invocation: WalletInvocation | None = None,
    *,
    grant: Grant | Mapping[str, Any] | None = None,
    profile_payload: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Return a byte-level DAG-CBOR fixture for the selected external stack."""

    if profile_payload is None:
        if invocation is None:
            raise ValueError("invocation or profile_payload is required")
        profile_payload = invocation_to_ucan_profile_payload(invocation, grant=grant)
    profile_payload = dict(profile_payload)
    block = _external_ucan_block_from_profile_payload(profile_payload)
    block_bytes = _dag_cbor_encode(block)
    return {
        "adapter": WALLET_UCAN_EXTERNAL_ADAPTER_ID,
        "target_stack": WALLET_UCAN_EXTERNAL_STACK_ID,
        "source_profile": WALLET_UCAN_PROFILE_ID,
        "codec": WALLET_UCAN_EXTERNAL_BLOCK_CODEC,
        "cid": _dag_cbor_cid(block_bytes),
        "bytes_sha256": hashlib.sha256(block_bytes).hexdigest(),
        "bytes_base64url": _base64url(block_bytes),
        "decoded": block,
    }


def wallet_ucan_conformance_fixture(
    invocation: WalletInvocation,
    *,
    grant: Grant | Mapping[str, Any] | None = None,
    token: str | None = None,
) -> Dict[str, Any]:
    """Return a deterministic conformance fixture for UCAN adapter tests."""

    profile_payload = invocation_to_ucan_profile_payload(invocation, grant=grant)
    ucan = profile_payload["ucan"]
    capability = ucan["att"][0]
    resolved_token = token or invocation_to_token(invocation)
    token_invocation = invocation_from_token(resolved_token)
    if token_invocation.to_dict() != invocation.to_dict():
        raise ValueError("Conformance fixture token does not encode the supplied invocation")
    return {
        "fixture": WALLET_UCAN_CONFORMANCE_FIXTURE_ID,
        "profile": WALLET_UCAN_PROFILE_ID,
        "token_prefix": WALLET_UCAN_TOKEN_PREFIX.rstrip("."),
        "token": resolved_token,
        "signature_payload_sha256": hashlib.sha256(
            canonical_bytes(invocation_signing_payload(invocation))
        ).hexdigest(),
        "expected": {
            "issuer": ucan["iss"],
            "audience": ucan["aud"],
            "capability": {
                "with": capability["with"],
                "can": capability["can"],
                "nb": dict(capability.get("nb") or {}),
            },
            "nonce": ucan["nnc"],
            "issued_at": ucan["fct"],
            "expires_at": ucan.get("exp"),
            "proofs": list(ucan.get("prf") or []),
            "signature": ucan["sig"],
        },
        "profile_payload": profile_payload,
        "external_adapters": {
            WALLET_UCAN_EXTERNAL_ADAPTER_KEY: wallet_ucan_external_adapter_fixture(
                profile_payload=profile_payload
            )
        },
    }


def validate_ucan_profile_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate and normalize a wallet UCAN-compatible inspection payload."""

    if not isinstance(payload, Mapping):
        raise ValueError("UCAN profile payload must be a mapping")
    if payload.get("profile") != WALLET_UCAN_PROFILE_ID:
        raise ValueError("Unsupported wallet UCAN profile")
    ucan = payload.get("ucan")
    if not isinstance(ucan, Mapping):
        raise ValueError("UCAN profile payload requires a ucan mapping")
    required_fields = {"iss", "aud", "att", "nnc", "fct", "sig", "prf"}
    missing = sorted(field for field in required_fields if field not in ucan)
    if missing:
        raise ValueError(f"UCAN profile payload missing fields: {', '.join(missing)}")
    attestations = ucan.get("att")
    if not isinstance(attestations, list) or not attestations:
        raise ValueError("UCAN profile payload requires at least one capability")
    if len(attestations) != 1:
        raise ValueError("UCAN profile payload requires exactly one capability")
    capability = attestations[0]
    if not isinstance(capability, Mapping):
        raise ValueError("UCAN capability must be a mapping")
    for field in ("with", "can"):
        if field not in capability:
            raise ValueError(f"UCAN capability missing {field}")
    caveats = capability.get("nb") or {}
    if not isinstance(caveats, Mapping):
        raise ValueError("UCAN capability caveats must be a mapping")
    proofs = ucan.get("prf")
    if not isinstance(proofs, list):
        raise ValueError("UCAN proof chain must be a list")

    normalized = {
        "issuer_did": str(ucan["iss"]),
        "audience_did": str(ucan["aud"]),
        "resource": str(capability["with"]),
        "ability": str(capability["can"]),
        "caveats": dict(caveats),
        "nonce": str(ucan["nnc"]),
        "issued_at": str(ucan["fct"]),
        "expires_at": str(ucan["exp"]) if ucan.get("exp") is not None else None,
        "signature": str(ucan["sig"]),
        "proofs": [str(item) for item in proofs],
    }

    wallet_invocation = payload.get("wallet_invocation")
    if isinstance(wallet_invocation, Mapping):
        comparisons = {
            "audience_did": normalized["audience_did"],
            "resource": normalized["resource"],
            "ability": normalized["ability"],
            "nonce": normalized["nonce"],
            "issued_at": normalized["issued_at"],
            "signature": normalized["signature"],
        }
        for key, expected in comparisons.items():
            if str(wallet_invocation.get(key)) != expected:
                raise ValueError(f"wallet_invocation {key} does not match UCAN payload")
        if dict(wallet_invocation.get("caveats") or {}) != normalized["caveats"]:
            raise ValueError("wallet_invocation caveats do not match UCAN payload")
        invocation_grant_id = wallet_invocation.get("grant_id")
        if invocation_grant_id is not None and str(invocation_grant_id) not in normalized["proofs"]:
            raise ValueError("wallet_invocation grant_id is not in UCAN proof chain")
        invocation_issuer = wallet_invocation.get("issuer_did")
        if invocation_issuer is not None and str(invocation_issuer) != normalized["issuer_did"]:
            raise ValueError("wallet_invocation issuer_did does not match UCAN payload")
        invocation_expiry = wallet_invocation.get("expires_at")
        if invocation_expiry is not None and str(invocation_expiry) != normalized["expires_at"]:
            raise ValueError("wallet_invocation expires_at does not match UCAN payload")

    wallet_grant = payload.get("wallet_grant")
    if isinstance(wallet_grant, Mapping):
        if str(wallet_grant.get("issuer_did")) != normalized["issuer_did"]:
            raise ValueError("wallet_grant issuer_did does not match UCAN payload")
        grant_id = wallet_grant.get("grant_id")
        if grant_id is not None and str(grant_id) not in normalized["proofs"]:
            raise ValueError("wallet_grant grant_id is not in UCAN proof chain")

    return normalized


def validate_wallet_ucan_external_adapter_fixture(
    adapter_fixture: Mapping[str, Any],
    *,
    profile_payload: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Validate a target-specific external UCAN adapter fixture."""

    if not isinstance(adapter_fixture, Mapping):
        raise ValueError("External UCAN adapter fixture must be a mapping")
    if adapter_fixture.get("adapter") != WALLET_UCAN_EXTERNAL_ADAPTER_ID:
        raise ValueError("Unsupported external UCAN adapter")
    if adapter_fixture.get("target_stack") != WALLET_UCAN_EXTERNAL_STACK_ID:
        raise ValueError("External UCAN adapter target_stack does not match")
    if adapter_fixture.get("source_profile") != WALLET_UCAN_PROFILE_ID:
        raise ValueError("External UCAN adapter source_profile does not match wallet profile")
    if adapter_fixture.get("codec") != WALLET_UCAN_EXTERNAL_BLOCK_CODEC:
        raise ValueError("External UCAN adapter codec does not match")

    encoded = adapter_fixture.get("bytes_base64url")
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("External UCAN adapter requires bytes_base64url")
    block_bytes = _base64url_decode(encoded)
    bytes_sha256 = hashlib.sha256(block_bytes).hexdigest()
    if adapter_fixture.get("bytes_sha256") != bytes_sha256:
        raise ValueError("External UCAN adapter bytes_sha256 does not match block bytes")
    cid = _dag_cbor_cid(block_bytes)
    if adapter_fixture.get("cid") != cid:
        raise ValueError("External UCAN adapter cid does not match block bytes")

    decoded = _dag_cbor_decode(block_bytes)
    if _dag_cbor_encode(decoded) != block_bytes:
        raise ValueError("External UCAN adapter block is not canonical DAG-CBOR")
    if dict(adapter_fixture.get("decoded") or {}) != decoded:
        raise ValueError("External UCAN adapter decoded block does not match block bytes")

    if profile_payload is not None:
        expected_block = _external_ucan_block_from_profile_payload(profile_payload)
        if decoded != expected_block:
            raise ValueError("External UCAN adapter block does not match wallet UCAN profile payload")

    normalized = validate_ucan_profile_payload(
        {
            "profile": WALLET_UCAN_PROFILE_ID,
            "ucan": decoded,
            **(
                {
                    "wallet_invocation": profile_payload.get("wallet_invocation"),
                    "wallet_grant": profile_payload.get("wallet_grant"),
                }
                if isinstance(profile_payload, Mapping)
                else {}
            ),
        }
    )
    return {
        "adapter": WALLET_UCAN_EXTERNAL_ADAPTER_ID,
        "target_stack": WALLET_UCAN_EXTERNAL_STACK_ID,
        "source_profile": WALLET_UCAN_PROFILE_ID,
        "codec": WALLET_UCAN_EXTERNAL_BLOCK_CODEC,
        "cid": cid,
        "bytes_sha256": bytes_sha256,
        **normalized,
    }


def validate_wallet_ucan_conformance_fixture(fixture: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate and normalize a complete wallet UCAN conformance fixture."""

    if not isinstance(fixture, Mapping):
        raise ValueError("UCAN conformance fixture must be a mapping")
    if fixture.get("fixture") != WALLET_UCAN_CONFORMANCE_FIXTURE_ID:
        raise ValueError("Unsupported wallet UCAN conformance fixture")
    if fixture.get("profile") != WALLET_UCAN_PROFILE_ID:
        raise ValueError("Conformance fixture profile does not match wallet UCAN profile")
    if fixture.get("token_prefix") != WALLET_UCAN_TOKEN_PREFIX.rstrip("."):
        raise ValueError("Conformance fixture token_prefix does not match wallet UCAN profile")

    token = fixture.get("token")
    if not isinstance(token, str) or not token.startswith(WALLET_UCAN_TOKEN_PREFIX):
        raise ValueError("Conformance fixture token is missing or uses an unsupported prefix")
    token_invocation = invocation_from_token(token)
    signature_payload_hash = hashlib.sha256(
        canonical_bytes(invocation_signing_payload(token_invocation))
    ).hexdigest()
    if fixture.get("signature_payload_sha256") != signature_payload_hash:
        raise ValueError("Conformance fixture signature_payload_sha256 does not match token")

    profile_payload = fixture.get("profile_payload")
    if not isinstance(profile_payload, Mapping):
        raise ValueError("Conformance fixture requires a profile_payload mapping")
    normalized = validate_ucan_profile_payload(profile_payload)

    expected = fixture.get("expected")
    if not isinstance(expected, Mapping):
        raise ValueError("Conformance fixture requires an expected mapping")
    capability = expected.get("capability")
    if not isinstance(capability, Mapping):
        raise ValueError("Conformance fixture expected.capability must be a mapping")

    comparisons = {
        "expected issuer": (expected.get("issuer"), normalized["issuer_did"]),
        "expected audience": (expected.get("audience"), normalized["audience_did"]),
        "expected nonce": (expected.get("nonce"), normalized["nonce"]),
        "expected issued_at": (expected.get("issued_at"), normalized["issued_at"]),
        "expected expires_at": (expected.get("expires_at"), normalized["expires_at"]),
        "expected signature": (expected.get("signature"), normalized["signature"]),
        "expected capability.with": (capability.get("with"), normalized["resource"]),
        "expected capability.can": (capability.get("can"), normalized["ability"]),
    }
    for label, (actual, expected_value) in comparisons.items():
        if actual != expected_value:
            raise ValueError(f"Conformance fixture {label} does not match profile payload")
    if dict(capability.get("nb") or {}) != normalized["caveats"]:
        raise ValueError("Conformance fixture expected capability caveats do not match profile payload")
    if [str(item) for item in expected.get("proofs", [])] != normalized["proofs"]:
        raise ValueError("Conformance fixture expected proofs do not match profile payload")

    external_adapters = fixture.get("external_adapters") or {}
    external_normalized = None
    if external_adapters:
        if not isinstance(external_adapters, Mapping):
            raise ValueError("Conformance fixture external_adapters must be a mapping")
        adapter_fixture = external_adapters.get(WALLET_UCAN_EXTERNAL_ADAPTER_KEY)
        if adapter_fixture is None:
            raise ValueError("Conformance fixture missing ucanto_w3up external adapter")
        external_normalized = validate_wallet_ucan_external_adapter_fixture(
            adapter_fixture,
            profile_payload=profile_payload,
        )

    token_comparisons = {
        "issuer_did": token_invocation.issuer_did,
        "audience_did": token_invocation.audience_did,
        "resource": token_invocation.resource,
        "ability": token_invocation.ability,
        "nonce": token_invocation.nonce,
        "issued_at": token_invocation.issued_at,
        "expires_at": token_invocation.expires_at,
        "signature": token_invocation.signature,
    }
    for key, value in token_comparisons.items():
        if value != normalized[key]:
            raise ValueError(f"Conformance fixture token {key} does not match profile payload")
    if dict(token_invocation.caveats or {}) != normalized["caveats"]:
        raise ValueError("Conformance fixture token caveats do not match profile payload")
    if token_invocation.grant_id not in normalized["proofs"]:
        raise ValueError("Conformance fixture token grant_id is not in proof chain")

    result = {
        "fixture": WALLET_UCAN_CONFORMANCE_FIXTURE_ID,
        "profile": WALLET_UCAN_PROFILE_ID,
        "token_invocation_id": token_invocation.invocation_id,
        "signature_payload_sha256": signature_payload_hash,
        **normalized,
    }
    if external_normalized is not None:
        result.update(
            {
                "external_adapter": external_normalized["adapter"],
                "external_target_stack": external_normalized["target_stack"],
                "external_cid": external_normalized["cid"],
                "external_bytes_sha256": external_normalized["bytes_sha256"],
            }
        )
    return result


def wallet_ucan_reference_conformance_fixture() -> Dict[str, Any]:
    """Return the built-in deterministic fixture used by CLI validation."""

    grant = Grant(
        grant_id="grant-wallet-ucan-v1-reference",
        issuer_did="did:key:wallet-owner-reference",
        audience_did="did:key:wallet-delegate-reference",
        resources=["wallet://wallet-reference/records/record-reference"],
        abilities=["record/analyze"],
        caveats={
            "purpose": "case_review",
            "record_ids": ["record-reference"],
            "output_types": ["summary"],
            "max_delegation_depth": 0,
        },
        proof_chain=["root-wallet-ucan-v1-reference"],
        created_at="2026-05-05T00:00:00+00:00",
        expires_at="2026-06-05T00:00:00+00:00",
    )
    invocation = WalletInvocation(
        invocation_id="invocation-wallet-ucan-v1-reference",
        grant_id=grant.grant_id,
        issuer_did=grant.issuer_did,
        audience_did=grant.audience_did,
        resource=grant.resources[0],
        ability="record/analyze",
        caveats={
            "purpose": "case_review",
            "record_ids": ["record-reference"],
            "output_types": ["summary"],
            "max_delegation_depth": 0,
        },
        issued_at="2026-05-05T00:00:00+00:00",
        expires_at="2026-06-05T00:00:00+00:00",
        nonce="nonce-wallet-ucan-v1-reference",
    )
    invocation.signature = sign_invocation(invocation, b"wallet-ucan-v1-reference-fixture-secret")
    return wallet_ucan_conformance_fixture(invocation, grant=grant)
