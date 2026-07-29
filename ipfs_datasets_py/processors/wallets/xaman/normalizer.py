"""Normalize raw Xaman/XUMM payload JSON into :class:`XamanPayload`.

Offline-first: does not open sockets or resolve credentials. Network and
account identity are bound at parse time; settlement remains unset until
:func:`settlement.verify_settlement_against_xrpl` is applied.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from ..errors import InvalidRequestError, NormalizationError
from ..xrpl.accounts import validate_classic_address
from ..xrpl.networks import XRPLNetwork
from .models import (
    PayloadStatus,
    SettlementVerdict,
    XamanPayload,
    resolve_payload_status_from_meta,
)
from .privacy import PayloadPrivacyPolicy

PROVIDER_KIND = "xaman-payload"
EXTENSION_NAMESPACE = "wallet.xaman"
EXTENSION_SCHEMA = "xaman-payload-v1"


def parse_xaman_payload(
    raw: Mapping[str, Any],
    *,
    network: XRPLNetwork = XRPLNetwork.MAINNET,
    privacy: PayloadPrivacyPolicy | None = None,
    require_network_match: bool = True,
) -> XamanPayload:
    """Parse a Xaman payload document into a normalized :class:`XamanPayload`."""

    if not isinstance(raw, Mapping):
        raise NormalizationError("payload must be a mapping")
    policy = privacy or PayloadPrivacyPolicy()

    meta = _as_mapping(raw.get("meta")) or _as_mapping(raw.get("Meta")) or {}
    payload_body = (
        _as_mapping(raw.get("payload"))
        or _as_mapping(raw.get("Payload"))
        or raw
    )
    response = (
        _as_mapping(raw.get("response"))
        or _as_mapping(raw.get("Response"))
        or {}
    )
    application = (
        _as_mapping(raw.get("application"))
        or _as_mapping(raw.get("Application"))
        or {}
    )

    uuid = (
        _optional_str(meta.get("uuid"))
        or _optional_str(meta.get("payload_uuid"))
        or _optional_str(raw.get("uuid"))
        or _optional_str(raw.get("payload_uuid"))
    )
    if not uuid:
        raise NormalizationError("payload uuid is required")

    bound_network = _resolve_network(
        raw, meta, response, default=network, require_match=require_network_match
    )
    status = resolve_payload_status_from_meta(meta) if meta else resolve_payload_status_from_meta(
        {
            "status": raw.get("status"),
            "signed": raw.get("signed"),
            "cancelled": raw.get("cancelled"),
            "expired": raw.get("expired"),
            "opened": raw.get("opened"),
            "resolved": raw.get("resolved"),
            "submitted": raw.get("submitted"),
            "validated": raw.get("validated"),
            "uuid": uuid,
        }
    )

    txjson = (
        _as_mapping(payload_body.get("txjson"))
        or _as_mapping(payload_body.get("request_json"))
        or _as_mapping(payload_body.get("tx_json"))
        or _as_mapping(raw.get("txjson"))
        or {}
    )

    account = _optional_str(
        response.get("account")
        or txjson.get("Account")
        or meta.get("account")
        or raw.get("account")
    )
    destination = _optional_str(
        txjson.get("Destination") or meta.get("destination") or raw.get("destination")
    )
    if account:
        try:
            account = validate_classic_address(
                account, network=bound_network
            ).address
        except (InvalidRequestError, NormalizationError) as exc:
            raise NormalizationError(f"invalid account: {exc}") from exc
    if destination:
        try:
            destination = validate_classic_address(
                destination, network=bound_network
            ).address
        except (InvalidRequestError, NormalizationError) as exc:
            raise NormalizationError(f"invalid destination: {exc}") from exc

    destination_tag = _optional_uint32(
        txjson.get("DestinationTag")
        if "DestinationTag" in txjson
        else meta.get("destination_tag")
    )
    transaction_type = _optional_str(
        txjson.get("TransactionType") or meta.get("transaction_type")
    )
    transaction_hash = _optional_str(
        response.get("txid")
        or response.get("tx_hash")
        or response.get("hash")
        or meta.get("txid")
        or raw.get("txid")
    )
    if transaction_hash:
        transaction_hash = transaction_hash.upper()

    application_uuid = _optional_str(
        application.get("uuid")
        or meta.get("application_uuid")
        or raw.get("application_uuid")
    )

    instruction = _optional_str(
        payload_body.get("custom_instruction")
        or meta.get("custom_instruction")
        or raw.get("custom_instruction")
    )
    instruction_fields = policy.apply_instruction(instruction)
    request_summary = policy.summarize_request(txjson)
    content_digest = policy.content_digest(
        uuid, instruction, request_summary, transaction_hash
    )
    raw_meta_digest = _digest_mapping(meta or {"uuid": uuid})

    return XamanPayload(
        payload_uuid=uuid,
        status=status,
        network=bound_network,
        account=account,
        destination=destination,
        destination_tag=destination_tag,
        transaction_type=transaction_type,
        transaction_hash=transaction_hash,
        application_uuid=application_uuid,
        user_token=_optional_str(meta.get("user_token") or raw.get("user_token")),
        created_at=_optional_datetime(meta.get("created_at") or raw.get("created_at")),
        resolved_at=_optional_datetime(
            meta.get("resolved_at") or response.get("resolved_at")
        ),
        expires_at=_optional_datetime(meta.get("expires_at") or meta.get("expired_at")),
        api_resolved=_truthy(meta.get("resolved")),
        api_signed=_truthy(meta.get("signed")),
        api_cancelled=_truthy(meta.get("cancelled") or meta.get("canceled")),
        api_expired=_truthy(meta.get("expired")),
        custom_instruction=instruction_fields["custom_instruction"],
        custom_instruction_redacted=instruction_fields["custom_instruction_redacted"],
        custom_instruction_truncated=instruction_fields["custom_instruction_truncated"],
        original_instruction_bytes=instruction_fields["original_instruction_bytes"],
        request_summary=request_summary,
        content_digest=content_digest,
        settlement=SettlementVerdict.NOT_APPLICABLE,
        settlement_detail=None,
        raw_meta_digest=raw_meta_digest,
        raw={"provider_kind": PROVIDER_KIND, "payload_uuid": uuid},
    )


def bind_network_account_payload(
    *,
    payload_uuid: str,
    network: XRPLNetwork,
    account: str | None,
    status: PayloadStatus = PayloadStatus.CREATED,
) -> XamanPayload:
    """Construct a minimal identity-bound payload shell."""

    if account:
        account = validate_classic_address(account, network=network).address
    return XamanPayload(
        payload_uuid=payload_uuid,
        status=status,
        network=network,
        account=account,
        settlement=SettlementVerdict.AWAITING_TXID
        if status
        not in {
            PayloadStatus.REJECTED,
            PayloadStatus.EXPIRED,
            PayloadStatus.CANCELLED,
        }
        else SettlementVerdict.NOT_APPLICABLE,
    )


def _resolve_network(
    raw: Mapping[str, Any],
    meta: Mapping[str, Any],
    response: Mapping[str, Any],
    *,
    default: XRPLNetwork,
    require_match: bool,
) -> XRPLNetwork:
    candidates = [
        raw.get("network"),
        meta.get("network"),
        meta.get("force_network"),
        response.get("dispatched_nodetype"),
        response.get("network"),
        raw.get("environment"),
    ]
    resolved: XRPLNetwork | None = None
    for candidate in candidates:
        parsed = _parse_network(candidate)
        if parsed is None:
            continue
        if resolved is None:
            resolved = parsed
        elif parsed is not resolved:
            raise NormalizationError(
                f"conflicting network identity: {resolved.value} vs {parsed.value}"
            )
    if resolved is None:
        return default
    if require_match and resolved is not default and default is not None:
        # Caller-selected processor network must match payload binding.
        if resolved is not default:
            raise NormalizationError(
                f"payload network {resolved.value} does not match "
                f"processor network {default.value}"
            )
    return resolved


def _parse_network(value: object) -> XRPLNetwork | None:
    if value is None:
        return None
    if isinstance(value, XRPLNetwork):
        return value
    text = str(value).strip().lower()
    if not text:
        return None
    aliases = {
        "mainnet": XRPLNetwork.MAINNET,
        "main": XRPLNetwork.MAINNET,
        "xrpl-mainnet": XRPLNetwork.MAINNET,
        "livenet": XRPLNetwork.MAINNET,
        "testnet": XRPLNetwork.TESTNET,
        "test": XRPLNetwork.TESTNET,
        "xrpl-testnet": XRPLNetwork.TESTNET,
        "devnet": XRPLNetwork.DEVNET,
        "dev": XRPLNetwork.DEVNET,
        "xrpl-devnet": XRPLNetwork.DEVNET,
    }
    if text in aliases:
        return aliases[text]
    # Xaman sometimes reports node type tokens.
    if "test" in text:
        return XRPLNetwork.TESTNET
    if "dev" in text:
        return XRPLNetwork.DEVNET
    if "main" in text or "live" in text:
        return XRPLNetwork.MAINNET
    return None


def _as_mapping(value: object) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    return None


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_uint32(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise NormalizationError(f"invalid destination tag: {value!r}") from exc
    if number < 0 or number > 0xFFFFFFFF:
        raise NormalizationError(f"destination tag out of range: {number}")
    return number


def _optional_datetime(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    text = str(value).strip()
    if not text:
        return None
    # Support trailing Z.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _digest_mapping(data: Mapping[str, Any]) -> str:
    payload = json.dumps(
        dict(data),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    )
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


__all__ = [
    "EXTENSION_NAMESPACE",
    "EXTENSION_SCHEMA",
    "PROVIDER_KIND",
    "bind_network_account_payload",
    "parse_xaman_payload",
]
