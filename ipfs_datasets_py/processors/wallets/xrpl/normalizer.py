"""Normalize XRPL-native transactions into chain-neutral ledger records.

AST entry: ``XRPLNormalizer``, ``delivered_amount``.
Partial payments must project ``meta.DeliveredAmount`` / ``delivered_amount``,
not the requested ``Amount``. Issued asset identity always includes currency
and issuer. Failed / unvalidated / unknown outcomes stay distinct.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from ..errors import InvalidRequestError, NormalizationError
from ..models import (
    AccountKind,
    AccountRef,
    ExactAmount,
    Finality,
    LedgerPosition,
    Provenance,
    RawPayloadRef,
    TransactionRecord,
    TransactionStatus,
    TransferKind,
    TransferRecord,
    VersionedExtension,
)
from ..protocols import Capabilities, Capability, OperationContext
from .amounts import exact_drops, exact_issued, parse_drops, require_no_float_amount
from .finality import XRPLFinalityPolicy
from .models import AmountKind, TxOutcome, XRPLAmount, XRPLTransaction
from .networks import (
    XRPLNetwork,
    assert_chain_matches,
    chain_ref_for,
    issued_asset,
    xrp_asset,
)
from .privacy import MemoPrivacyPolicy

EXTENSION_NAMESPACE = "xrpl"
EXTENSION_SCHEMA = "wallet-xrpl-tx-v1"
PROVIDER_KIND = "xrpl-json-rpc"

# Payment flags (XRPL)
_TF_PARTIAL_PAYMENT = 0x00020000


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _payload_digest(payload: Mapping[str, Any]) -> RawPayloadRef:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return RawPayloadRef(
        digest=f"sha256:{digest}",
        media_type="application/json",
        byte_length=len(body.encode("utf-8")),
    )


def _parse_amount(raw: Any, *, field: str = "Amount") -> XRPLAmount | None:
    if raw is None:
        return None
    require_no_float_amount(raw, field=field)
    if isinstance(raw, (str, int)):
        drops = parse_drops(raw, field=field)
        return XRPLAmount(kind=AmountKind.XRP, value=str(drops))
    if isinstance(raw, Mapping):
        currency = raw.get("currency")
        issuer = raw.get("issuer")
        value = raw.get("value")
        if currency is None or issuer is None or value is None:
            raise NormalizationError(
                f"{field} issued amount requires currency, issuer, and value"
            )
        require_no_float_amount(value, field=f"{field}.value")
        return XRPLAmount(
            kind=AmountKind.ISSUED,
            value=str(value).strip(),
            currency=str(currency).strip(),
            issuer=str(issuer).strip(),
        )
    raise NormalizationError(f"{field} must be drops or issued currency object")


def _amount_to_exact(amount: XRPLAmount) -> ExactAmount:
    if amount.kind is AmountKind.XRP:
        return exact_drops(amount.value, field="drops")
    return exact_issued(amount.value, field="issued_value")


def _amount_to_asset(amount: XRPLAmount, chain) -> object:
    if amount.kind is AmountKind.XRP:
        return xrp_asset(chain)
    # Match ExactAmount decimals for this projection.
    exact = exact_issued(amount.value)
    return issued_asset(
        chain,
        currency=amount.currency or "",
        issuer=amount.issuer or "",
        decimals=exact.decimals,
        symbol=amount.currency,
    )


def _is_partial_payment(tx_json: Mapping[str, Any]) -> bool:
    flags = tx_json.get("Flags") or 0
    try:
        return bool(int(flags) & _TF_PARTIAL_PAYMENT)
    except (TypeError, ValueError):
        return False


def _outcome_from_meta(
    *,
    validated: bool,
    meta: Mapping[str, Any] | None,
) -> tuple[TxOutcome, str | None]:
    if not validated:
        return TxOutcome.UNVALIDATED, None
    if meta is None:
        return TxOutcome.UNKNOWN, None
    result = meta.get("TransactionResult") or meta.get("transaction_result")
    if result is None:
        return TxOutcome.UNKNOWN, None
    code = str(result)
    if code == "tesSUCCESS":
        return TxOutcome.VALIDATED_SUCCESS, code
    # tec/tef/tel/tem/ter are distinct failure classes; all map to validated_failed.
    if code.startswith(("tec", "tef", "tel", "tem", "ter")):
        return TxOutcome.VALIDATED_FAILED, code
    return TxOutcome.UNKNOWN, code


def delivered_amount(
    tx_json: Mapping[str, Any],
    meta: Mapping[str, Any] | None,
) -> XRPLAmount | None:
    """Resolve the amount actually delivered for a Payment (or similar).

    Prefer ``meta.delivered_amount`` / ``DeliveredAmount`` over ``Amount`` so
    partial payments do not overstate settlement.
    """

    if meta is not None:
        for key in ("delivered_amount", "DeliveredAmount"):
            if key in meta and meta[key] is not None:
                return _parse_amount(meta[key], field=key)
    # Non-partial payments: Amount is the delivered amount when successful.
    if "Amount" in tx_json:
        return _parse_amount(tx_json.get("Amount"), field="Amount")
    return None


def parse_account_tx_entry(
    entry: Mapping[str, Any],
    *,
    network: XRPLNetwork,
    privacy: MemoPrivacyPolicy | None = None,
    validated_hint: bool | None = None,
) -> XRPLTransaction:
    """Parse one ``account_tx`` transaction entry into :class:`XRPLTransaction`."""

    if not isinstance(entry, Mapping):
        raise NormalizationError("account_tx entry must be a mapping")
    tx_json = entry.get("tx") or entry.get("tx_json") or entry
    if not isinstance(tx_json, Mapping):
        raise NormalizationError("transaction body must be a mapping")
    meta = entry.get("meta") or entry.get("metaData")
    if meta is not None and not isinstance(meta, Mapping):
        raise NormalizationError("meta must be a mapping when present")

    tx_hash = str(tx_json.get("hash") or entry.get("hash") or "").strip()
    if not tx_hash:
        raise NormalizationError("transaction missing hash")

    account = str(tx_json.get("Account") or "").strip()
    if not account:
        raise NormalizationError("transaction missing Account")
    tx_type = str(tx_json.get("TransactionType") or "Unknown").strip()
    sequence_raw = tx_json.get("Sequence")
    if sequence_raw is None:
        raise NormalizationError("transaction missing Sequence")
    sequence = int(sequence_raw)

    validated = entry.get("validated")
    if validated is None:
        validated = validated_hint if validated_hint is not None else False
    validated = bool(validated)

    outcome, result_code = _outcome_from_meta(validated=validated, meta=meta)
    partial = _is_partial_payment(tx_json)

    amount = _parse_amount(tx_json.get("Amount"), field="Amount") if "Amount" in tx_json else None
    send_max = (
        _parse_amount(tx_json.get("SendMax"), field="SendMax")
        if "SendMax" in tx_json
        else None
    )
    # Always prefer delivered_amount for settlement projection.
    delivered = delivered_amount(tx_json, meta if isinstance(meta, Mapping) else None)

    dest = tx_json.get("Destination")
    dest_tag = tx_json.get("DestinationTag")
    src_tag = tx_json.get("SourceTag")
    fee = tx_json.get("Fee")

    ledger_index = entry.get("ledger_index")
    if ledger_index is None:
        ledger_index = tx_json.get("ledger_index")
    ledger_hash = entry.get("ledger_hash") or tx_json.get("ledger_hash")
    tx_index = None
    if isinstance(meta, Mapping) and "TransactionIndex" in meta:
        tx_index = int(meta["TransactionIndex"])

    policy = privacy or MemoPrivacyPolicy()
    memos = policy.apply_memos(tx_json.get("Memos"))

    close_time = None
    # Optional ISO close time from expanded fixtures.
    raw_close = entry.get("close_time_iso") or tx_json.get("date_iso")
    if isinstance(raw_close, str) and raw_close:
        try:
            close_time = datetime.fromisoformat(raw_close.replace("Z", "+00:00"))
        except ValueError:
            close_time = None

    return XRPLTransaction(
        hash=tx_hash,
        account=account,
        transaction_type=tx_type,
        sequence=sequence,
        outcome=outcome,
        network=network,
        fee_drops=str(fee) if fee is not None else None,
        destination=str(dest).strip() if dest else None,
        destination_tag=int(dest_tag) if dest_tag is not None else None,
        source_tag=int(src_tag) if src_tag is not None else None,
        amount=amount,
        delivered_amount=delivered,
        send_max=send_max,
        partial_payment=partial,
        memos=memos,
        ledger_index=int(ledger_index) if ledger_index is not None else None,
        ledger_hash=str(ledger_hash) if ledger_hash else None,
        transaction_index=tx_index,
        close_time_iso=close_time,
        transaction_result=result_code,
        validated=validated,
        raw=dict(entry),
    )


@dataclass
class XRPLNormalizer:
    """Pure conversion from XRPL-native values to versioned domain records."""

    network: XRPLNetwork = XRPLNetwork.MAINNET
    provider: str = "xrpl-json-rpc"
    finality_policy: XRPLFinalityPolicy | None = None
    privacy: MemoPrivacyPolicy = field(default_factory=MemoPrivacyPolicy)
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.network, XRPLNetwork):
            raise InvalidRequestError("network must be an XRPLNetwork")
        self._chain = chain_ref_for(self.network)
        self._finality = self.finality_policy or XRPLFinalityPolicy(network=self.network)

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            provider=self.provider,
            chain_namespaces=frozenset({self._chain.namespace}),
            features=frozenset(
                {
                    Capability.WALLET_HISTORY,
                    Capability.LEDGER_RANGE,
                    Capability.BALANCES,
                    Capability.TOKEN_TRANSFERS,
                    Capability.FINALITY,
                    Capability.RAW_PAYLOADS,
                }
            ),
            metadata={
                "network": self.network.value,
                "provider_family": PROVIDER_KIND,
                "account_model": True,
                "supports_sign": False,
                "supports_submit": False,
                "xaman_payloads": False,
            },
        )

    @property
    def chain(self):
        return self._chain

    def normalize(
        self,
        records: Sequence[object],
        *,
        context: OperationContext,
        scope: str | None = None,
    ) -> Sequence[object]:
        """Normalize a bounded batch without performing I/O."""

        context.check_active()
        if len(records) > context.limits.max_items:
            raise InvalidRequestError("normalize batch exceeds max_items")
        observed = self.observed_at or _utc_now()
        request_scope = scope or context.request_id
        out: list[object] = []
        for item in records:
            tx = self._coerce_tx(item)
            out.extend(
                self._project_tx(
                    tx,
                    context=context,
                    observed_at=observed,
                    scope=request_scope,
                )
            )
        return tuple(out)

    def _coerce_tx(self, item: object) -> XRPLTransaction:
        if isinstance(item, XRPLTransaction):
            if item.network is not self.network:
                raise NormalizationError(
                    f"transaction network {item.network.value} does not match "
                    f"normalizer network {self.network.value}"
                )
            return item
        if isinstance(item, Mapping):
            return parse_account_tx_entry(
                item, network=self.network, privacy=self.privacy
            )
        raise NormalizationError(
            f"unsupported XRPL native record type: {type(item)!r}"
        )

    def _project_tx(
        self,
        tx: XRPLTransaction,
        *,
        context: OperationContext,
        observed_at: datetime,
        scope: str,
    ) -> list[object]:
        assert_chain_matches(self._chain, self.network)
        finality = self._finality.finality_for_transaction(tx)
        position = LedgerPosition(
            sequence=tx.ledger_index,
            hash=tx.ledger_hash,
            transaction_index=tx.transaction_index,
        )
        raw_payload = _payload_digest(dict(tx.raw)) if tx.raw else None
        provenance = Provenance(
            provider=self.provider,
            provider_kind=PROVIDER_KIND,
            request_id=context.request_id,
            scope=scope,
            observed_at=observed_at,
            raw_payload=raw_payload,
        )

        participants: list[AccountRef] = [
            AccountRef(
                chain=self._chain,
                address=tx.account,
                kind=AccountKind.ADDRESS,
            )
        ]
        if tx.destination and tx.destination != tx.account:
            participants.append(
                AccountRef(
                    chain=self._chain,
                    address=tx.destination,
                    kind=AccountKind.ADDRESS,
                )
            )

        fee = exact_drops(tx.fee_drops) if tx.fee_drops is not None else None
        extension = VersionedExtension(
            schema_version=EXTENSION_SCHEMA,
            data={
                "hash": tx.hash,
                "transaction_type": tx.transaction_type,
                "sequence": tx.sequence,
                "outcome": tx.outcome.value,
                "transaction_result": tx.transaction_result,
                "validated": tx.validated,
                "partial_payment": tx.partial_payment,
                "destination_tag": (
                    tx.destination_tag
                    if self.privacy.preserve_destination_tags
                    else None
                ),
                "source_tag": (
                    tx.source_tag if self.privacy.preserve_source_tags else None
                ),
                "memos": [m.to_dict() for m in tx.memos],
                "amount": tx.amount.to_dict() if tx.amount else None,
                "delivered_amount": (
                    tx.delivered_amount.to_dict() if tx.delivered_amount else None
                ),
                "send_max": tx.send_max.to_dict() if tx.send_max else None,
                "supports_sign": False,
                "supports_submit": False,
                "xaman_payloads": False,
            },
        )

        if tx.outcome is TxOutcome.VALIDATED_SUCCESS:
            status = TransactionStatus.SUCCEEDED
        elif tx.outcome is TxOutcome.VALIDATED_FAILED:
            status = TransactionStatus.FAILED
        else:
            status = TransactionStatus.UNKNOWN

        records: list[object] = [
            TransactionRecord(
                chain=self._chain,
                provenance=provenance,
                ledger_position=position,
                finality=finality,
                extensions={EXTENSION_NAMESPACE: extension},
                transaction_hash=tx.hash,
                status=status,
                participants=tuple(participants),
                fee=fee,
                block_time=tx.close_time_iso,
            )
        ]

        # Settlement transfer uses delivered_amount (critical for partial payments).
        settlement = tx.delivered_amount or (
            tx.amount if tx.outcome is TxOutcome.VALIDATED_SUCCESS else None
        )
        transfer_index = 0
        if settlement is not None and tx.transaction_type == "Payment":
            asset = _amount_to_asset(settlement, self._chain)
            amount = _amount_to_exact(settlement)
            # Align decimals: issued_asset already matched exact decimals.
            if amount.decimals != asset.decimals:  # type: ignore[union-attr]
                asset = issued_asset(
                    self._chain,
                    currency=settlement.currency or "",
                    issuer=settlement.issuer or "",
                    decimals=amount.decimals,
                    symbol=settlement.currency,
                ) if settlement.kind is AmountKind.ISSUED else xrp_asset(self._chain)
                if settlement.kind is AmountKind.XRP:
                    amount = exact_drops(settlement.value)
            kind = (
                TransferKind.TOKEN
                if settlement.kind is AmountKind.ISSUED
                else TransferKind.NATIVE
            )
            records.append(
                TransferRecord(
                    chain=self._chain,
                    provenance=provenance,
                    ledger_position=position,
                    finality=finality,
                    extensions={EXTENSION_NAMESPACE: extension},
                    transaction_hash=tx.hash,
                    transfer_index=transfer_index,
                    asset=asset,  # type: ignore[arg-type]
                    amount=amount,
                    source_account=AccountRef(
                        chain=self._chain,
                        address=tx.account,
                        kind=AccountKind.ADDRESS,
                    ),
                    destination_account=(
                        AccountRef(
                            chain=self._chain,
                            address=tx.destination,
                            kind=AccountKind.ADDRESS,
                        )
                        if tx.destination
                        else None
                    ),
                    transfer_kind=kind,
                )
            )
            transfer_index += 1

        if fee is not None and fee.base_units != "0":
            records.append(
                TransferRecord(
                    chain=self._chain,
                    provenance=provenance,
                    ledger_position=position,
                    finality=finality,
                    extensions={EXTENSION_NAMESPACE: extension},
                    transaction_hash=tx.hash,
                    transfer_index=transfer_index,
                    asset=xrp_asset(self._chain),
                    amount=fee,
                    source_account=AccountRef(
                        chain=self._chain,
                        address=tx.account,
                        kind=AccountKind.ADDRESS,
                    ),
                    destination_account=None,
                    transfer_kind=TransferKind.FEE,
                )
            )

        return records


__all__ = [
    "EXTENSION_NAMESPACE",
    "EXTENSION_SCHEMA",
    "PROVIDER_KIND",
    "XRPLNormalizer",
    "delivered_amount",
    "parse_account_tx_entry",
]
