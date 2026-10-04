"""High-level XRPL wallet/ledger processor composition.

Composes :class:`XRPLLedgerProvider`, :class:`XRPLNormalizer`, and
:class:`XRPLFinalityPolicy` behind the shared wallet-domain protocols.
No signing, submission, or Xaman payload path exists.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..errors import InvalidRequestError
from ..models import BalanceSnapshot, ExactAmount, Finality, LedgerPosition, Provenance
from ..protocols import (
    BoundedRequest,
    Capabilities,
    Capability,
    OperationContext,
    RecordBatch,
)
from .accounts import describe_account
from .finality import XRPLFinalityPolicy
from .models import XRPLTransaction
from .networks import XRPLNetwork, chain_ref_for, xrp_asset
from .normalizer import XRPLNormalizer, parse_account_tx_entry
from .privacy import MemoPrivacyPolicy
from .provider import XRPLLedgerProvider


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class XRPLWalletProcessor:
    """Read-only XRPL processor with validated-ledger finality and export hooks."""

    network: XRPLNetwork = XRPLNetwork.MAINNET
    provider: XRPLLedgerProvider | None = None
    normalizer: XRPLNormalizer | None = None
    finality_policy: XRPLFinalityPolicy | None = None
    privacy: MemoPrivacyPolicy | None = None
    name: str = "xrpl-wallet-processor"

    def __post_init__(self) -> None:
        if not isinstance(self.network, XRPLNetwork):
            raise InvalidRequestError("network must be an XRPLNetwork")
        self._chain = chain_ref_for(self.network)
        self._privacy = self.privacy or MemoPrivacyPolicy()
        self._finality = self.finality_policy or XRPLFinalityPolicy(
            network=self.network
        )
        self._normalizer = self.normalizer or XRPLNormalizer(
            network=self.network,
            finality_policy=self._finality,
            privacy=self._privacy,
        )
        self._provider = self.provider
        features = {
            Capability.BALANCES,
            Capability.FINALITY,
            Capability.DATASET_EXPORT,
            Capability.TOKEN_TRANSFERS,
        }
        if self._provider is not None:
            features |= {
                Capability.WALLET_HISTORY,
                Capability.LEDGER_RANGE,
                Capability.REORG_RECOVERY,
                Capability.RAW_PAYLOADS,
            }
        self._capabilities = Capabilities(
            provider=self.name,
            chain_namespaces=frozenset({self._chain.namespace}),
            features=frozenset(features),
            metadata={
                "network": self.network.value,
                "account_model": True,
                "supports_sign": False,
                "supports_submit": False,
                "supports_broadcast": False,
                "xaman_payloads": False,
                "marker_pagination": True,
                "validated_only_final": True,
            },
        )

    @property
    def capabilities(self) -> Capabilities:
        return self._capabilities

    @property
    def chain(self):
        return self._chain

    @property
    def ledger_provider(self) -> XRPLLedgerProvider | None:
        return self._provider

    def validate_address(self, address: str) -> dict[str, Any]:
        descriptor = describe_account(address, network=self.network)
        return descriptor.to_dict()

    def normalize_transactions(
        self,
        transactions: Sequence[object],
        *,
        context: OperationContext,
    ) -> tuple[object, ...]:
        """Normalize native or account_tx-shaped transactions offline."""

        context.check_active()
        native: list[XRPLTransaction] = []
        for item in transactions:
            if isinstance(item, XRPLTransaction):
                native.append(item)
            elif isinstance(item, Mapping):
                native.append(
                    parse_account_tx_entry(
                        item, network=self.network, privacy=self._privacy
                    )
                )
            else:
                raise InvalidRequestError(
                    f"unsupported transaction type: {type(item)!r}"
                )
        normalized = self._normalizer.normalize(native, context=context)
        return tuple(normalized)

    def balance_snapshot(
        self,
        address: str,
        *,
        context: OperationContext,
        drops: int,
        ledger_index: int | None = None,
        ledger_hash: str | None = None,
        validated: bool = True,
    ) -> BalanceSnapshot:
        """Project an exact drop balance (caller-supplied or provider-fetched)."""

        context.check_active()
        descriptor = describe_account(address, network=self.network)
        from ..models import AccountKind, AccountRef

        account = AccountRef(
            chain=self._chain,
            address=descriptor.address,
            kind=AccountKind.ADDRESS,
        )
        amount = ExactAmount.from_int(int(drops), decimals=6)
        finality = Finality.FINALIZED if validated else Finality.PENDING
        return BalanceSnapshot(
            chain=self._chain,
            provenance=Provenance(
                provider=self.name,
                provider_kind="xrpl-balance",
                request_id=context.request_id,
                scope=f"balance:{descriptor.address}",
                observed_at=_utc_now(),
            ),
            ledger_position=LedgerPosition(sequence=ledger_index, hash=ledger_hash),
            finality=finality,
            account=account,
            asset=xrp_asset(self._chain),
            amount=amount,
        )

    async def ingest_wallet(
        self,
        request: BoundedRequest,
    ) -> AsyncIterator[RecordBatch]:
        if self._provider is None:
            raise InvalidRequestError("provider is required for ingest_wallet")
        request.context.check_active()
        async for batch in self._provider.ingest_wallet(request):
            request.context.check_active()
            normalized = self.normalize_transactions(
                batch.records, context=request.context
            )
            out = RecordBatch(
                records=tuple(normalized),
                next_cursor=batch.next_cursor,
                response_bytes=batch.response_bytes,
            )
            out.enforce(request.context.limits)
            yield out

    async def ingest_ledger(
        self,
        request: BoundedRequest,
    ) -> AsyncIterator[RecordBatch]:
        if self._provider is None:
            raise InvalidRequestError("provider is required for ingest_ledger")
        request.context.check_active()
        async for batch in self._provider.ingest_ledger(request):
            request.context.check_active()
            normalized = self.normalize_transactions(
                batch.records, context=request.context
            )
            out = RecordBatch(
                records=tuple(normalized),
                next_cursor=batch.next_cursor,
                response_bytes=batch.response_bytes,
            )
            out.enforce(request.context.limits)
            yield out


__all__ = [
    "XRPLWalletProcessor",
]
