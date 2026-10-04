"""XRPL settlement verification for Xaman payloads.

Xaman API success is never settlement. Transaction facts are verified only
through the composed XRPL processor / ledger records.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..errors import InvalidRequestError
from ..xrpl.models import TxOutcome, XRPLTransaction
from ..xrpl.networks import XRPLNetwork
from .models import (
    AccountActivityCorrelation,
    PayloadStatus,
    SettlementVerdict,
    XamanPayload,
)


@dataclass(frozen=True, slots=True)
class SettlementEvidence:
    """Evidence used to decide settlement; always explicit and inspectable."""

    transaction_hash: str | None
    validated: bool
    outcome: str | None
    ledger_index: int | None
    account: str | None
    network: str | None
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_hash": self.transaction_hash,
            "validated": self.validated,
            "outcome": self.outcome,
            "ledger_index": self.ledger_index,
            "account": self.account,
            "network": self.network,
            "source": self.source,
        }


def verify_settlement_against_xrpl(
    payload: XamanPayload,
    *,
    xrpl_transactions: Sequence[XRPLTransaction] | Sequence[Mapping[str, Any]] = (),
) -> XamanPayload:
    """Bind and verify a payload against XRPL transaction facts.

    Rules:

    * No transaction hash → ``AWAITING_TXID`` (even if API signed/submitted).
    * Hash present but not found in XRPL evidence and API success →
      ``API_SUCCESS_ONLY`` (explicitly not settlement).
    * Hash found with validated success → ``XRPL_VALIDATED``.
    * Hash found with validated failure → ``XRPL_FAILED``.
    * Hash found unvalidated → ``XRPL_UNVALIDATED``.
    * Network mismatch → ``NETWORK_MISMATCH``.
    * Account mismatch (when both sides bound) → ``ACCOUNT_MISMATCH``.
    """

    if not isinstance(payload, XamanPayload):
        raise InvalidRequestError("payload must be XamanPayload")

    tx_hash = payload.transaction_hash
    if not tx_hash:
        if payload.is_api_success:
            return payload.with_settlement(
                SettlementVerdict.API_SUCCESS_ONLY,
                detail="api_success_without_txid",
            )
        if payload.status in {
            PayloadStatus.CREATED,
            PayloadStatus.OPENED,
            PayloadStatus.REJECTED,
            PayloadStatus.EXPIRED,
            PayloadStatus.CANCELLED,
            PayloadStatus.UNKNOWN,
        }:
            return payload.with_settlement(
                SettlementVerdict.NOT_APPLICABLE
                if payload.status
                in {
                    PayloadStatus.REJECTED,
                    PayloadStatus.EXPIRED,
                    PayloadStatus.CANCELLED,
                }
                else SettlementVerdict.AWAITING_TXID,
                detail=f"status={payload.status.value}",
            )
        return payload.with_settlement(
            SettlementVerdict.AWAITING_TXID,
            detail="missing_transaction_hash",
        )

    matches = _find_matching(tx_hash, xrpl_transactions)
    if not matches:
        if payload.is_api_success:
            return payload.with_settlement(
                SettlementVerdict.API_SUCCESS_ONLY,
                detail="api_success_txid_not_on_ledger_evidence",
            )
        return payload.with_settlement(
            SettlementVerdict.UNKNOWN,
            detail="txid_not_found_in_xrpl_evidence",
        )

    # Prefer the first exact hash match after network/account checks.
    for match in matches:
        network = match.get("network")
        if network is not None and network != payload.network.value:
            return payload.with_settlement(
                SettlementVerdict.NETWORK_MISMATCH,
                detail=f"payload={payload.network.value} ledger={network}",
            )
        ledger_account = match.get("account")
        if (
            payload.account
            and ledger_account
            and _normalize_account(payload.account)
            != _normalize_account(str(ledger_account))
        ):
            # Destination-bound payloads may sign as a different account;
            # only fail when the payload account is set and conflicts with
            # the ledger transaction Account field.
            if payload.destination and _normalize_account(
                str(ledger_account)
            ) == _normalize_account(payload.destination):
                pass  # destination signed/received path
            else:
                return payload.with_settlement(
                    SettlementVerdict.ACCOUNT_MISMATCH,
                    detail=(
                        f"payload_account={payload.account} "
                        f"ledger_account={ledger_account}"
                    ),
                )

        if match.get("validated") is True and match.get("outcome") == TxOutcome.VALIDATED_SUCCESS.value:
            return payload.with_settlement(
                SettlementVerdict.XRPL_VALIDATED,
                detail=f"ledger_index={match.get('ledger_index')}",
            )
        if match.get("validated") is True and match.get("outcome") == TxOutcome.VALIDATED_FAILED.value:
            return payload.with_settlement(
                SettlementVerdict.XRPL_FAILED,
                detail=match.get("transaction_result") or "validated_failed",
            )
        if match.get("validated") is not True:
            return payload.with_settlement(
                SettlementVerdict.XRPL_UNVALIDATED,
                detail=match.get("outcome") or "unvalidated",
            )

    return payload.with_settlement(
        SettlementVerdict.UNKNOWN,
        detail="no_conclusive_match",
    )


def correlate_account_activity(
    payload: XamanPayload,
    *,
    account: str,
    xrpl_transactions: Sequence[XRPLTransaction] | Sequence[Mapping[str, Any]] = (),
) -> AccountActivityCorrelation:
    """Correlate payload identity with XRPL activity for a classic account."""

    if not account or not str(account).strip():
        raise InvalidRequestError("account must not be empty")
    account = str(account).strip()
    settled = verify_settlement_against_xrpl(
        payload, xrpl_transactions=xrpl_transactions
    )
    matching: list[str] = []
    for match in _find_matching(payload.transaction_hash or "", xrpl_transactions):
        h = match.get("hash")
        if h:
            matching.append(str(h).upper())
    # Also collect hashes involving the account even without payload txid.
    if not matching:
        for item in _iter_normalized(xrpl_transactions):
            if _involves_account(item, account):
                h = item.get("hash")
                if h:
                    matching.append(str(h).upper())
    notes = None
    if settled.is_api_success and not settled.is_ledger_settled:
        notes = "api_success_is_not_settlement"
    return AccountActivityCorrelation(
        payload_uuid=payload.payload_uuid,
        account=account,
        network=payload.network,
        transaction_hash=payload.transaction_hash,
        payload_status=payload.status,
        settlement=settled.settlement,
        matching_ledger_hashes=tuple(dict.fromkeys(matching)),
        notes=notes,
    )


def evidence_from_xrpl_transaction(tx: XRPLTransaction) -> SettlementEvidence:
    return SettlementEvidence(
        transaction_hash=tx.hash,
        validated=tx.validated,
        outcome=tx.outcome.value,
        ledger_index=tx.ledger_index,
        account=tx.account,
        network=tx.network.value,
        source="xrpl_transaction",
    )


def _find_matching(
    tx_hash: str,
    transactions: Sequence[XRPLTransaction] | Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not tx_hash:
        return []
    want = tx_hash.strip().upper()
    out: list[dict[str, Any]] = []
    for item in _iter_normalized(transactions):
        h = str(item.get("hash") or "").upper()
        if h == want:
            out.append(item)
    return out


def _iter_normalized(
    transactions: Sequence[XRPLTransaction] | Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in transactions:
        if isinstance(item, XRPLTransaction):
            out.append(
                {
                    "hash": item.hash,
                    "account": item.account,
                    "destination": item.destination,
                    "validated": item.validated,
                    "outcome": item.outcome.value,
                    "ledger_index": item.ledger_index,
                    "network": item.network.value,
                    "transaction_result": item.transaction_result,
                }
            )
        elif isinstance(item, Mapping):
            network = item.get("network")
            if isinstance(network, XRPLNetwork):
                network = network.value
            outcome = item.get("outcome")
            if isinstance(outcome, TxOutcome):
                outcome = outcome.value
            out.append(
                {
                    "hash": str(item.get("hash") or item.get("transaction_hash") or ""),
                    "account": item.get("account"),
                    "destination": item.get("destination"),
                    "validated": bool(item.get("validated")),
                    "outcome": outcome,
                    "ledger_index": item.get("ledger_index"),
                    "network": network,
                    "transaction_result": item.get("transaction_result"),
                }
            )
    return out


def _involves_account(item: Mapping[str, Any], account: str) -> bool:
    want = _normalize_account(account)
    for key in ("account", "destination"):
        value = item.get(key)
        if value and _normalize_account(str(value)) == want:
            return True
    return False


def _normalize_account(address: str) -> str:
    return address.strip()


__all__ = [
    "SettlementEvidence",
    "correlate_account_activity",
    "evidence_from_xrpl_transaction",
    "verify_settlement_against_xrpl",
]
