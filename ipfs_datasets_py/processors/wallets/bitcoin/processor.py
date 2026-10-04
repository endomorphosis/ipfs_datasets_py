"""High-level Bitcoin wallet/ledger processor composition.

Composes :class:`BitcoinLedgerProvider`, :class:`BitcoinNormalizer`,
:class:`UtxoSet`, and :class:`BitcoinFinalityPolicy` behind the shared
wallet-domain protocols. No signing or broadcast path exists.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
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
from .finality import BitcoinFinalityPolicy
from .models import BitcoinTransaction, TxStatus
from .networks import BitcoinNetwork, btc_asset, chain_ref_for
from .normalizer import BitcoinNormalizer
from .provider import BitcoinLedgerProvider
from .scripts import describe_address
from .utxo_set import UtxoSet


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class BitcoinWalletProcessor:
    """Read-only Bitcoin processor with UTXO-driven balances and reorg reverse."""

    network: BitcoinNetwork = BitcoinNetwork.MAINNET
    provider: BitcoinLedgerProvider | None = None
    normalizer: BitcoinNormalizer | None = None
    finality_policy: BitcoinFinalityPolicy | None = None
    utxo_set: UtxoSet | None = None
    name: str = "bitcoin-wallet-processor"

    def __post_init__(self) -> None:
        if not isinstance(self.network, BitcoinNetwork):
            raise InvalidRequestError("network must be a BitcoinNetwork")
        self._chain = chain_ref_for(self.network)
        self._finality = self.finality_policy or BitcoinFinalityPolicy(
            network=self.network
        )
        self._normalizer = self.normalizer or BitcoinNormalizer(
            network=self.network,
            finality_policy=self._finality,
        )
        self._utxos = self.utxo_set if self.utxo_set is not None else UtxoSet()
        self._provider = self.provider
        features = {
            Capability.BALANCES,
            Capability.FINALITY,
            Capability.REORG_RECOVERY,
            Capability.DATASET_EXPORT,
        }
        if self._provider is not None:
            features |= {
                Capability.WALLET_HISTORY,
                Capability.LEDGER_RANGE,
            }
        self._capabilities = Capabilities(
            provider=self.name,
            chain_namespaces=frozenset({self._chain.namespace}),
            features=frozenset(features),
            metadata={
                "network": self.network.value,
                "utxo_model": True,
                "supports_psbt": False,
                "supports_sign": False,
                "supports_broadcast": False,
                "ownership_clustering": False,
                "confirmation_policy": {
                    "confirmed": self._finality.thresholds.confirmed,
                    "safe": self._finality.thresholds.safe,
                    "finalized": self._finality.thresholds.finalized,
                },
            },
        )

    @property
    def capabilities(self) -> Capabilities:
        return self._capabilities

    @property
    def chain(self):
        return self._chain

    @property
    def utxos(self) -> UtxoSet:
        return self._utxos

    @property
    def ledger_provider(self) -> BitcoinLedgerProvider | None:
        return self._provider

    def validate_address(self, address: str) -> dict[str, Any]:
        descriptor = describe_address(address, network=self.network)
        return descriptor.to_dict()

    def apply_native_transaction(
        self,
        tx: BitcoinTransaction,
        *,
        allow_missing_inputs: bool = False,
    ) -> dict[str, Any]:
        """Apply a native transaction to the UTXO set (offline path)."""

        if tx.network is not self.network:
            raise InvalidRequestError(
                f"transaction network {tx.network.value} mismatches processor "
                f"network {self.network.value}"
            )
        mark_replaced = tx.replaces
        result = self._utxos.apply_transaction(
            tx,
            allow_missing_inputs=allow_missing_inputs,
            mark_replaced=mark_replaced,
        )
        return result.to_dict()

    def reverse_transaction(self, txid: str) -> dict[str, Any]:
        """Reverse UTXO effects for a reorged transaction."""

        return self._utxos.reverse_transaction(txid).to_dict()

    def reverse_from_height(self, height: int) -> tuple[str, ...]:
        return self._utxos.reverse_from_height(height)

    def balance_sats(self, address: str | None = None) -> int:
        return self._utxos.balance_sats(address)

    def balance_snapshot(
        self,
        address: str,
        *,
        context: OperationContext,
        head_height: int | None = None,
        block_hash: str | None = None,
    ) -> BalanceSnapshot:
        """Project an exact satoshi balance from the UTXO set."""

        context.check_active()
        descriptor = describe_address(address, network=self.network)
        assert descriptor.address is not None
        from ..models import AccountKind, AccountRef

        account = AccountRef(
            chain=self._chain,
            address=descriptor.address,
            kind=AccountKind.ADDRESS,
        )
        amount = ExactAmount.from_int(
            self._utxos.balance_sats(descriptor.address),
            decimals=8,
        )
        finality = Finality.OBSERVED
        if head_height is not None:
            finality = self._finality.finality_for_confirmations(0)
        return BalanceSnapshot(
            chain=self._chain,
            provenance=Provenance(
                provider=self.name,
                provider_kind="utxo-set",
                request_id=context.request_id,
                scope=f"balance:{descriptor.address}",
                observed_at=_utc_now(),
            ),
            ledger_position=LedgerPosition(sequence=head_height, hash=block_hash),
            finality=finality,
            account=account,
            asset=btc_asset(self._chain),
            amount=amount,
        )

    def normalize_transactions(
        self,
        transactions: Sequence[object],
        *,
        context: OperationContext,
        head_height: int | None = None,
        apply_utxos: bool = True,
        allow_missing_inputs: bool = True,
    ) -> tuple[object, ...]:
        """Normalize transactions and optionally advance the UTXO set."""

        context.check_active()
        native: list[BitcoinTransaction] = []
        for item in transactions:
            if isinstance(item, BitcoinTransaction):
                native.append(item)
            elif isinstance(item, Mapping):
                from .normalizer import parse_esplora_transaction

                native.append(
                    parse_esplora_transaction(item, network=self.network)
                )
            else:
                raise InvalidRequestError(
                    f"unsupported transaction type: {type(item)!r}"
                )
        if apply_utxos:
            for tx in native:
                if tx.status is TxStatus.REPLACED:
                    continue
                self._utxos.apply_transaction(
                    tx,
                    allow_missing_inputs=allow_missing_inputs,
                    mark_replaced=tx.replaces,
                )
        normalized = self._normalizer.normalize(
            native,
            context=context,
            head_height=head_height,
        )
        return tuple(normalized)

    async def ingest_wallet(
        self,
        request: BoundedRequest,
    ) -> AsyncIterator[RecordBatch]:
        """Stream normalized batches for a wallet address via the provider."""

        if self._provider is None:
            raise InvalidRequestError("provider is required for ingest_wallet")
        request.context.check_active()
        head = await self._provider.ledger_head(context=request.context)
        head_height = int(head["sequence"]) if isinstance(head, Mapping) else None
        async for batch in self._provider.ingest_wallet(request):
            request.context.check_active()
            normalized = self.normalize_transactions(
                batch.records,
                context=request.context,
                head_height=head_height,
                apply_utxos=True,
                allow_missing_inputs=True,
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
        head = await self._provider.ledger_head(context=request.context)
        head_height = int(head["sequence"]) if isinstance(head, Mapping) else None
        async for batch in self._provider.ingest_ledger(request):
            request.context.check_active()
            normalized = self.normalize_transactions(
                batch.records,
                context=request.context,
                head_height=head_height,
                apply_utxos=True,
                allow_missing_inputs=True,
            )
            out = RecordBatch(
                records=tuple(normalized),
                next_cursor=batch.next_cursor,
                response_bytes=batch.response_bytes,
            )
            out.enforce(request.context.limits)
            yield out


__all__ = [
    "BitcoinWalletProcessor",
]
