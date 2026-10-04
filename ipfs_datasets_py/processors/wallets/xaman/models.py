"""Xaman-native payload lifecycle models (WALPROC-G210).

Lifecycle states remain distinct. API-reported success is never settlement.
Ledger settlement is represented separately via :class:`SettlementVerdict`
and is only set when XRPL validates (or rejects) a bound transaction hash.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

from ..errors import InvalidRequestError
from ..xrpl.networks import XRPLNetwork


class PayloadStatus(StrEnum):
    """Distinct Xaman payload lifecycle states.

    These values must never be collapsed into each other or into ledger
    finality. In particular, ``SIGNED`` / ``SUBMITTED`` are API lifecycle
    facts, not XRPL settlement.
    """

    CREATED = "created"
    OPENED = "opened"
    SIGNED = "signed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    SUBMITTED = "submitted"
    VALIDATED = "validated"
    FAILED = "failed"
    UNKNOWN = "unknown"


class SettlementVerdict(StrEnum):
    """Ledger settlement relative to a payload — never derived from API alone."""

    NOT_APPLICABLE = "not_applicable"
    AWAITING_TXID = "awaiting_txid"
    API_SUCCESS_ONLY = "api_success_only"
    XRPL_VALIDATED = "xrpl_validated"
    XRPL_FAILED = "xrpl_failed"
    XRPL_UNVALIDATED = "xrpl_unvalidated"
    NETWORK_MISMATCH = "network_mismatch"
    ACCOUNT_MISMATCH = "account_mismatch"
    UNKNOWN = "unknown"


# Ordered for documentation; all members must remain distinct values.
ALL_PAYLOAD_STATUSES: frozenset[PayloadStatus] = frozenset(PayloadStatus)

# API lifecycle states that must never be treated as ledger settlement.
NON_SETTLEMENT_API_STATUSES: frozenset[PayloadStatus] = frozenset(
    {
        PayloadStatus.CREATED,
        PayloadStatus.OPENED,
        PayloadStatus.SIGNED,
        PayloadStatus.REJECTED,
        PayloadStatus.EXPIRED,
        PayloadStatus.CANCELLED,
        PayloadStatus.SUBMITTED,
        PayloadStatus.FAILED,
        PayloadStatus.UNKNOWN,
    }
)


def parse_payload_status(raw: object) -> PayloadStatus:
    """Map heterogeneous Xaman/XUMM status fields to :class:`PayloadStatus`."""

    if isinstance(raw, PayloadStatus):
        return raw
    if raw is None:
        return PayloadStatus.UNKNOWN
    text = str(raw).strip().lower()
    if not text:
        return PayloadStatus.UNKNOWN
    aliases = {
        "create": PayloadStatus.CREATED,
        "created": PayloadStatus.CREATED,
        "open": PayloadStatus.OPENED,
        "opened": PayloadStatus.OPENED,
        "app_opened": PayloadStatus.OPENED,
        "sign": PayloadStatus.SIGNED,
        "signed": PayloadStatus.SIGNED,
        "reject": PayloadStatus.REJECTED,
        "rejected": PayloadStatus.REJECTED,
        "declined": PayloadStatus.REJECTED,
        "expire": PayloadStatus.EXPIRED,
        "expired": PayloadStatus.EXPIRED,
        "cancel": PayloadStatus.CANCELLED,
        "cancelled": PayloadStatus.CANCELLED,
        "canceled": PayloadStatus.CANCELLED,
        "submit": PayloadStatus.SUBMITTED,
        "submitted": PayloadStatus.SUBMITTED,
        "dispatched": PayloadStatus.SUBMITTED,
        "validate": PayloadStatus.VALIDATED,
        "validated": PayloadStatus.VALIDATED,
        "fail": PayloadStatus.FAILED,
        "failed": PayloadStatus.FAILED,
        "error": PayloadStatus.FAILED,
        "unknown": PayloadStatus.UNKNOWN,
    }
    return aliases.get(text, PayloadStatus.UNKNOWN)


def resolve_payload_status_from_meta(meta: Mapping[str, Any] | None) -> PayloadStatus:
    """Derive lifecycle status from a Xaman ``meta`` object without claiming settlement.

    Priority prefers terminal user/API decisions over intermediate flags.
    ``validated`` is only returned when the meta explicitly marks validation
    and is still **not** ledger settlement by itself.
    """

    if not meta:
        return PayloadStatus.UNKNOWN

    explicit = meta.get("status") or meta.get("payload_status") or meta.get("resolved_status")
    if explicit is not None and str(explicit).strip():
        return parse_payload_status(explicit)

    # Boolean flag cascade from Xaman payload meta shape.
    if _truthy(meta.get("expired")):
        return PayloadStatus.EXPIRED
    if _truthy(meta.get("cancelled")) or _truthy(meta.get("canceled")):
        return PayloadStatus.CANCELLED
    if _truthy(meta.get("rejected")) or _truthy(meta.get("declined")):
        return PayloadStatus.REJECTED
    if _truthy(meta.get("failed")) or _truthy(meta.get("error")):
        return PayloadStatus.FAILED
    # Explicit validated flag on the API object is still not XRPL settlement.
    if _truthy(meta.get("validated")) and _truthy(meta.get("resolved")):
        return PayloadStatus.VALIDATED
    if _truthy(meta.get("submitted")) or _truthy(meta.get("dispatched")):
        return PayloadStatus.SUBMITTED
    if _truthy(meta.get("signed")):
        return PayloadStatus.SIGNED
    if _truthy(meta.get("opened")) or _truthy(meta.get("app_opened")):
        return PayloadStatus.OPENED
    if _truthy(meta.get("created")) or meta.get("uuid") or meta.get("payload_uuid"):
        return PayloadStatus.CREATED
    return PayloadStatus.UNKNOWN


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True, slots=True)
class XamanPayload:
    """Normalized Xaman payload metadata with bound network/account identity.

    Does not hold private keys, seed material, or signing authority. Custom
    payload content may be redacted under privacy policy.
    """

    payload_uuid: str
    status: PayloadStatus
    network: XRPLNetwork
    account: str | None = None
    destination: str | None = None
    destination_tag: int | None = None
    transaction_type: str | None = None
    transaction_hash: str | None = None
    application_uuid: str | None = None
    user_token: str | None = None  # opaque handle; never a secret material field
    created_at: datetime | None = None
    resolved_at: datetime | None = None
    expires_at: datetime | None = None
    api_resolved: bool = False
    api_signed: bool = False
    api_cancelled: bool = False
    api_expired: bool = False
    # Content after privacy policy (may be redacted / size-bounded).
    custom_instruction: str | None = None
    custom_instruction_redacted: bool = False
    custom_instruction_truncated: bool = False
    original_instruction_bytes: int | None = None
    # Redacted projection of txjson / request body keys only.
    request_summary: Mapping[str, Any] = field(default_factory=dict, hash=False)
    content_digest: str | None = None
    settlement: SettlementVerdict = SettlementVerdict.NOT_APPLICABLE
    settlement_detail: str | None = None
    raw_meta_digest: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        if not isinstance(self.payload_uuid, str) or not self.payload_uuid.strip():
            raise InvalidRequestError("payload_uuid must not be empty")
        object.__setattr__(self, "payload_uuid", self.payload_uuid.strip())
        if not isinstance(self.status, PayloadStatus):
            raise InvalidRequestError("status must be PayloadStatus")
        if not isinstance(self.network, XRPLNetwork):
            raise InvalidRequestError("network must be XRPLNetwork")
        if not isinstance(self.settlement, SettlementVerdict):
            raise InvalidRequestError("settlement must be SettlementVerdict")
        if self.destination_tag is not None and (
            isinstance(self.destination_tag, bool)
            or not isinstance(self.destination_tag, int)
            or self.destination_tag < 0
            or self.destination_tag > 0xFFFFFFFF
        ):
            raise InvalidRequestError("destination_tag must be a uint32")
        if self.transaction_hash is not None:
            text = self.transaction_hash.strip().upper()
            if not text:
                object.__setattr__(self, "transaction_hash", None)
            else:
                object.__setattr__(self, "transaction_hash", text)
        if self.account is not None:
            object.__setattr__(self, "account", self.account.strip() or None)
        if self.destination is not None:
            object.__setattr__(self, "destination", self.destination.strip() or None)
        object.__setattr__(
            self, "request_summary", MappingProxyType(dict(self.request_summary))
        )
        object.__setattr__(self, "raw", MappingProxyType(dict(self.raw)))

    @property
    def is_api_success(self) -> bool:
        """True when the Xaman API reports a successful lifecycle resolution."""

        return self.status in {
            PayloadStatus.SIGNED,
            PayloadStatus.SUBMITTED,
            PayloadStatus.VALIDATED,
        } or (self.api_resolved and self.api_signed)

    @property
    def is_ledger_settled(self) -> bool:
        """True only when XRPL validated the bound transaction."""

        return self.settlement is SettlementVerdict.XRPL_VALIDATED

    def with_settlement(
        self,
        verdict: SettlementVerdict,
        *,
        detail: str | None = None,
    ) -> XamanPayload:
        """Return a copy with an updated settlement verdict (immutable)."""

        return XamanPayload(
            payload_uuid=self.payload_uuid,
            status=self.status,
            network=self.network,
            account=self.account,
            destination=self.destination,
            destination_tag=self.destination_tag,
            transaction_type=self.transaction_type,
            transaction_hash=self.transaction_hash,
            application_uuid=self.application_uuid,
            user_token=self.user_token,
            created_at=self.created_at,
            resolved_at=self.resolved_at,
            expires_at=self.expires_at,
            api_resolved=self.api_resolved,
            api_signed=self.api_signed,
            api_cancelled=self.api_cancelled,
            api_expired=self.api_expired,
            custom_instruction=self.custom_instruction,
            custom_instruction_redacted=self.custom_instruction_redacted,
            custom_instruction_truncated=self.custom_instruction_truncated,
            original_instruction_bytes=self.original_instruction_bytes,
            request_summary=dict(self.request_summary),
            content_digest=self.content_digest,
            settlement=verdict,
            settlement_detail=detail,
            raw_meta_digest=self.raw_meta_digest,
            raw=dict(self.raw),
        )

    def to_dict(self) -> dict[str, Any]:
        """Public, redacted projection suitable for export."""

        return {
            "payload_uuid": self.payload_uuid,
            "status": self.status.value,
            "network": self.network.value,
            "account": self.account,
            "destination": self.destination,
            "destination_tag": self.destination_tag,
            "transaction_type": self.transaction_type,
            "transaction_hash": self.transaction_hash,
            "application_uuid": self.application_uuid,
            "api_resolved": self.api_resolved,
            "api_signed": self.api_signed,
            "api_cancelled": self.api_cancelled,
            "api_expired": self.api_expired,
            "custom_instruction": self.custom_instruction,
            "custom_instruction_redacted": self.custom_instruction_redacted,
            "custom_instruction_truncated": self.custom_instruction_truncated,
            "original_instruction_bytes": self.original_instruction_bytes,
            "request_summary": dict(self.request_summary),
            "content_digest": self.content_digest,
            "settlement": self.settlement.value,
            "settlement_detail": self.settlement_detail,
            "is_api_success": self.is_api_success,
            "is_ledger_settled": self.is_ledger_settled,
            "raw_meta_digest": self.raw_meta_digest,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


@dataclass(frozen=True, slots=True)
class AccountActivityCorrelation:
    """Correlation of a payload with XRPL account activity for one account."""

    payload_uuid: str
    account: str
    network: XRPLNetwork
    transaction_hash: str | None
    payload_status: PayloadStatus
    settlement: SettlementVerdict
    matching_ledger_hashes: tuple[str, ...] = ()
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "payload_uuid": self.payload_uuid,
            "account": self.account,
            "network": self.network.value,
            "transaction_hash": self.transaction_hash,
            "payload_status": self.payload_status.value,
            "settlement": self.settlement.value,
            "matching_ledger_hashes": list(self.matching_ledger_hashes),
            "notes": self.notes,
        }


__all__ = [
    "ALL_PAYLOAD_STATUSES",
    "AccountActivityCorrelation",
    "NON_SETTLEMENT_API_STATUSES",
    "PayloadStatus",
    "SettlementVerdict",
    "XamanPayload",
    "parse_payload_status",
    "resolve_payload_status_from_meta",
]
