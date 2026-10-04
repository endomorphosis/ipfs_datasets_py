"""Bounded, read-only Ethereum JSON-RPC provider.

The provider deliberately exposes only observation methods.  A caller supplies
the JSON-RPC transport, endpoint, operation context, and finite range.  No
credentials are read and no network I/O happens during import or construction.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
import json
import re
from typing import Any, Protocol

from ..errors import (
    InvalidRequestError,
    NormalizationError,
    ProviderError,
    ResourceLimitError,
    UnsupportedCapabilityError,
)
from ..models import ChainRef
from ..protocols import (
    BoundedRequest,
    Capabilities,
    Capability,
    OperationContext,
    RecordBatch,
)


EVM_NAMESPACE = "eip155"
ETHEREUM_MAINNET_CHAIN_ID = 1
ETHEREUM_MAINNET_GENESIS_HASH = (
    "0xd4e56740f876aef8c010b86a40d5f56745a118d0906a34e69aec8c0db1cb8fa3"
)

_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_HASH_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
_QUANTITY_RE = re.compile(r"^0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)$")


class JsonRpcTransport(Protocol):
    """Minimal injected transport surface required by this provider."""

    async def json_rpc(
        self,
        url: str,
        method: str,
        params: Mapping[str, object] | Sequence[object],
        *,
        context: OperationContext,
        request_id: int | str = 1,
        headers: Mapping[str, str] | None = None,
    ) -> object:
        """Execute one bounded JSON-RPC call."""


class EthereumIdentityError(ProviderError):
    """The provider is attached to a different chain or genesis."""


def parse_quantity(value: object, *, field: str = "quantity") -> int:
    """Parse a canonical EIP-1474 quantity without float coercion."""

    if not isinstance(value, str) or not _QUANTITY_RE.fullmatch(value):
        raise NormalizationError(f"{field} must be a canonical 0x quantity")
    return int(value[2:], 16)


def encode_quantity(value: int) -> str:
    """Encode a non-negative integer as a canonical EIP-1474 quantity."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidRequestError("quantity must be a non-negative integer")
    return hex(value)


def normalize_address(value: object, *, field: str = "address") -> str:
    """Return a stable lowercase EVM address.

    Mixed-case checksum validation is intentionally optional because it needs a
    Keccak implementation.  Hex shape is always enforced and canonical output
    is lowercase.
    """

    if not isinstance(value, str) or not _ADDRESS_RE.fullmatch(value):
        raise NormalizationError(f"{field} must be a 20-byte 0x address")
    return value.lower()


def normalize_hash(value: object, *, field: str = "hash") -> str:
    if not isinstance(value, str) or not _HASH_RE.fullmatch(value):
        raise NormalizationError(f"{field} must be a 32-byte 0x hash")
    return value.lower()


@dataclass(frozen=True, slots=True)
class EvmNetwork:
    """Expected EVM network identity and native-asset metadata."""

    chain_id: int
    network: str
    genesis_hash: str
    native_symbol: str = "ETH"
    native_decimals: int = 18

    def __post_init__(self) -> None:
        if (
            isinstance(self.chain_id, bool)
            or not isinstance(self.chain_id, int)
            or self.chain_id <= 0
        ):
            raise InvalidRequestError("chain_id must be a positive integer")
        if not isinstance(self.network, str) or not self.network.strip():
            raise InvalidRequestError("network must not be empty")
        object.__setattr__(
            self,
            "genesis_hash",
            normalize_hash(self.genesis_hash, field="genesis_hash"),
        )
        if not isinstance(self.native_symbol, str) or not self.native_symbol.strip():
            raise InvalidRequestError("native_symbol must not be empty")
        if (
            isinstance(self.native_decimals, bool)
            or not isinstance(self.native_decimals, int)
            or not 0 <= self.native_decimals <= 255
        ):
            raise InvalidRequestError("native_decimals must be between 0 and 255")

    def to_chain_ref(self) -> ChainRef:
        return ChainRef(
            namespace=EVM_NAMESPACE,
            network=self.network,
            chain_id=str(self.chain_id),
            genesis_hash=self.genesis_hash,
        )


ETHEREUM_MAINNET = EvmNetwork(
    chain_id=ETHEREUM_MAINNET_CHAIN_ID,
    network="ethereum-mainnet",
    genesis_hash=ETHEREUM_MAINNET_GENESIS_HASH,
)


@dataclass(frozen=True, slots=True)
class EvmHead:
    """Latest head plus optional explicit safe/finalized anchors."""

    latest: Mapping[str, Any]
    safe: Mapping[str, Any] | None
    finalized: Mapping[str, Any] | None
    explicit_tags_supported: bool

    @property
    def sequence(self) -> int:
        return parse_quantity(self.latest.get("number"), field="latest.number")

    @property
    def hash(self) -> str:
        return normalize_hash(self.latest.get("hash"), field="latest.hash")


@dataclass(frozen=True, slots=True)
class EvmBlockBundle:
    """One block with receipts and optional per-transaction traces."""

    block: Mapping[str, Any]
    receipts: tuple[Mapping[str, Any], ...]
    traces: Mapping[str, tuple[Mapping[str, Any], ...] | None]
    trace_capability: bool


class _RequestBudget:
    def __init__(self, context: OperationContext) -> None:
        self.context = context
        self.used = 0

    def consume(self) -> None:
        self.context.check_active()
        self.used += 1
        if self.used > self.context.limits.max_requests:
            raise ResourceLimitError("Ethereum JSON-RPC request budget exceeded")


class EthereumLedgerProvider:
    """Read-only EVM account and finite ledger-range provider."""

    __slots__ = (
        "_endpoint",
        "_include_traces",
        "_network",
        "_provider_name",
        "_transport",
        "_validated_chain",
    )

    def __init__(
        self,
        transport: JsonRpcTransport,
        *,
        endpoint: str,
        network: EvmNetwork = ETHEREUM_MAINNET,
        provider_name: str = "ethereum-json-rpc",
        include_traces: bool = False,
    ) -> None:
        if not callable(getattr(transport, "json_rpc", None)):
            raise TypeError("transport must provide async json_rpc")
        if not isinstance(endpoint, str) or not endpoint.startswith(("http://", "https://")):
            raise InvalidRequestError("endpoint must be an HTTP(S) URL")
        if not isinstance(network, EvmNetwork):
            raise InvalidRequestError("network must be an EvmNetwork")
        if not isinstance(provider_name, str) or not provider_name.strip():
            raise InvalidRequestError("provider_name must not be empty")
        self._transport = transport
        self._endpoint = endpoint
        self._network = network
        self._provider_name = provider_name
        self._include_traces = bool(include_traces)
        self._validated_chain: ChainRef | None = None

    def __repr__(self) -> str:
        return (
            f"EthereumLedgerProvider(provider_name={self._provider_name!r}, "
            f"chain_id={self._network.chain_id!r}, endpoint=<redacted>)"
        )

    @property
    def chain(self) -> ChainRef:
        return self._network.to_chain_ref()

    @property
    def capabilities(self) -> Capabilities:
        features = {
            Capability.WALLET_HISTORY,
            Capability.LEDGER_RANGE,
            Capability.BALANCES,
            Capability.TOKEN_TRANSFERS,
            Capability.CONTRACT_EVENTS,
            Capability.RAW_PAYLOADS,
            Capability.FINALITY,
            Capability.REORG_RECOVERY,
            Capability.DATASET_EXPORT,
        }
        if self._include_traces:
            features.add(Capability.INTERNAL_TRANSFERS)
        return Capabilities(
            provider=self._provider_name,
            chain_namespaces=frozenset({EVM_NAMESPACE}),
            features=frozenset(features),
            metadata={
                "chain_id": str(self._network.chain_id),
                "network": self._network.network,
                "genesis_hash": self._network.genesis_hash,
                "trace_capability": self._include_traces,
                "read_only": True,
            },
        )

    async def _call(
        self,
        method: str,
        params: Sequence[object],
        *,
        context: OperationContext,
        budget: _RequestBudget | None = None,
    ) -> object:
        if budget is not None:
            budget.consume()
        else:
            context.check_active()
        return await self._transport.json_rpc(
            self._endpoint,
            method,
            params,
            context=context,
            request_id=context.request_id,
        )

    async def _validate_identity(
        self,
        *,
        context: OperationContext,
        budget: _RequestBudget,
    ) -> ChainRef:
        chain_id = parse_quantity(
            await self._call("eth_chainId", (), context=context, budget=budget),
            field="eth_chainId",
        )
        genesis = await self._call(
            "eth_getBlockByNumber",
            ("0x0", False),
            context=context,
            budget=budget,
        )
        if not isinstance(genesis, Mapping):
            raise EthereumIdentityError("provider returned no genesis block")
        genesis_hash = normalize_hash(genesis.get("hash"), field="genesis.hash")
        if chain_id != self._network.chain_id:
            raise EthereumIdentityError(
                f"provider chain id {chain_id} does not match expected "
                f"{self._network.chain_id}"
            )
        if genesis_hash != self._network.genesis_hash:
            raise EthereumIdentityError(
                "provider genesis hash does not match configured network"
            )
        self._validated_chain = self.chain
        return self._validated_chain

    async def validate_identity(self, *, context: OperationContext) -> ChainRef:
        """Bind this provider to both ``eth_chainId`` and block-zero hash."""

        return await self._validate_identity(
            context=context,
            budget=_RequestBudget(context),
        )

    async def _ensure_identity(
        self,
        *,
        context: OperationContext,
        budget: _RequestBudget,
    ) -> ChainRef:
        if self._validated_chain is None:
            return await self._validate_identity(context=context, budget=budget)
        return self._validated_chain

    async def validate_address(
        self,
        address: str,
        *,
        context: OperationContext,
    ) -> str:
        context.check_active()
        return normalize_address(address)

    async def get_balance(
        self,
        address: str,
        *,
        block: int | str = "latest",
        context: OperationContext,
    ) -> int:
        budget = _RequestBudget(context)
        await self._ensure_identity(context=context, budget=budget)
        normalized = await self.validate_address(address, context=context)
        tag = encode_quantity(block) if isinstance(block, int) else block
        if tag not in {"latest", "safe", "finalized", "pending", "earliest"}:
            if not isinstance(tag, str) or not _QUANTITY_RE.fullmatch(tag):
                raise InvalidRequestError("block must be a canonical tag or quantity")
        return parse_quantity(
            await self._call(
                "eth_getBalance",
                (normalized, tag),
                context=context,
                budget=budget,
            ),
            field="eth_getBalance",
        )

    async def get_block(
        self,
        block: int | str,
        *,
        full_transactions: bool = True,
        context: OperationContext,
        budget: _RequestBudget | None = None,
    ) -> Mapping[str, Any]:
        tag = encode_quantity(block) if isinstance(block, int) else block
        if not isinstance(tag, str):
            raise InvalidRequestError("block must be an integer or tag")
        result = await self._call(
            "eth_getBlockByNumber",
            (tag, full_transactions),
            context=context,
            budget=budget,
        )
        if not isinstance(result, Mapping):
            raise ProviderError(f"Ethereum block {tag!r} is unavailable")
        return result

    async def get_receipt(
        self,
        transaction_hash: str,
        *,
        context: OperationContext,
        budget: _RequestBudget | None = None,
    ) -> Mapping[str, Any]:
        tx_hash = normalize_hash(transaction_hash, field="transaction_hash")
        result = await self._call(
            "eth_getTransactionReceipt",
            (tx_hash,),
            context=context,
            budget=budget,
        )
        if not isinstance(result, Mapping):
            raise ProviderError("Ethereum transaction receipt is unavailable")
        return result

    async def trace_transaction(
        self,
        transaction_hash: str,
        *,
        context: OperationContext,
        budget: _RequestBudget | None = None,
    ) -> tuple[Mapping[str, Any], ...]:
        if not self._include_traces:
            raise UnsupportedCapabilityError(
                "internal transfers require the optional trace capability"
            )
        tx_hash = normalize_hash(transaction_hash, field="transaction_hash")
        result = await self._call(
            "trace_transaction",
            (tx_hash,),
            context=context,
            budget=budget,
        )
        if not isinstance(result, Sequence) or isinstance(result, (str, bytes)):
            raise ProviderError("trace_transaction returned a malformed result")
        if any(not isinstance(item, Mapping) for item in result):
            raise ProviderError("trace_transaction entries must be mappings")
        return tuple(result)  # type: ignore[arg-type]

    async def ledger_head(self, *, context: OperationContext) -> EvmHead:
        """Prefer explicit safe/finalized tags and label fallback explicitly."""

        budget = _RequestBudget(context)
        await self._ensure_identity(context=context, budget=budget)
        latest = await self.get_block(
            "latest", full_transactions=False, context=context, budget=budget
        )
        safe: Mapping[str, Any] | None = None
        finalized: Mapping[str, Any] | None = None
        explicit = True
        try:
            safe = await self.get_block(
                "safe", full_transactions=False, context=context, budget=budget
            )
            finalized = await self.get_block(
                "finalized", full_transactions=False, context=context, budget=budget
            )
        except ProviderError:
            explicit = False
            safe = None
            finalized = None
        return EvmHead(
            latest=latest,
            safe=safe,
            finalized=finalized,
            explicit_tags_supported=explicit,
        )

    async def _bundle(
        self,
        sequence: int,
        *,
        context: OperationContext,
        budget: _RequestBudget,
    ) -> EvmBlockBundle:
        block = await self.get_block(
            sequence,
            full_transactions=True,
            context=context,
            budget=budget,
        )
        transactions = block.get("transactions")
        if not isinstance(transactions, Sequence) or isinstance(
            transactions, (str, bytes)
        ):
            raise ProviderError("Ethereum block transactions must be a sequence")
        if len(transactions) > context.limits.max_items:
            raise ResourceLimitError("Ethereum block exceeds max_items")

        receipts: list[Mapping[str, Any]] = []
        traces: dict[str, tuple[Mapping[str, Any], ...] | None] = {}
        for transaction in transactions:
            if not isinstance(transaction, Mapping):
                raise ProviderError("Ethereum transaction must be a mapping")
            tx_hash = normalize_hash(transaction.get("hash"), field="transaction.hash")
            receipts.append(
                await self.get_receipt(tx_hash, context=context, budget=budget)
            )
            if self._include_traces:
                try:
                    traces[tx_hash] = await self.trace_transaction(
                        tx_hash,
                        context=context,
                        budget=budget,
                    )
                except ProviderError:
                    # Trace APIs are optional even when requested; ingestion of
                    # transactions/receipts/logs must remain available.
                    traces[tx_hash] = None
            else:
                traces[tx_hash] = None
        return EvmBlockBundle(
            block=block,
            receipts=tuple(receipts),
            traces=traces,
            trace_capability=self._include_traces,
        )

    @staticmethod
    def _response_bytes(bundle: EvmBlockBundle) -> int:
        return len(
            json.dumps(
                {
                    "block": bundle.block,
                    "receipts": bundle.receipts,
                    "traces": bundle.traces,
                },
                separators=(",", ":"),
            ).encode("utf-8")
        )

    async def ingest_ledger(
        self,
        request: BoundedRequest,
    ) -> AsyncIterator[RecordBatch]:
        """Stream an explicit inclusive block range as one bundle per batch."""

        request.context.check_active()
        if request.start_position is None or request.end_position is None:
            raise InvalidRequestError(
                "Ethereum ledger ingestion requires start_position and end_position"
            )
        count = request.end_position - request.start_position + 1
        if count > request.context.limits.max_pages:
            raise ResourceLimitError("Ethereum block range exceeds max_pages")
        budget = _RequestBudget(request.context)
        await self._ensure_identity(context=request.context, budget=budget)
        for sequence in range(request.start_position, request.end_position + 1):
            bundle = await self._bundle(
                sequence,
                context=request.context,
                budget=budget,
            )
            batch = RecordBatch(
                records=(bundle,),
                response_bytes=self._response_bytes(bundle),
            )
            batch.enforce(request.context.limits)
            yield batch

    async def ingest_wallet(
        self,
        request: BoundedRequest,
    ) -> AsyncIterator[RecordBatch]:
        """Scan a finite range and retain bundles containing the account."""

        address = normalize_address(request.scope, field="scope")
        async for batch in self.ingest_ledger(request):
            bundle = batch.records[0]
            assert isinstance(bundle, EvmBlockBundle)
            transactions = bundle.block.get("transactions") or ()
            logs = [
                log
                for receipt in bundle.receipts
                for log in (receipt.get("logs") or ())
                if isinstance(log, Mapping)
            ]
            involved = any(
                isinstance(tx, Mapping)
                and (
                    str(tx.get("from") or "").lower() == address
                    or str(tx.get("to") or "").lower() == address
                )
                for tx in transactions
            ) or any(
                address[2:] in str(topic).lower()
                for log in logs
                for topic in (log.get("topics") or ())
            )
            if involved:
                yield batch


__all__ = [
    "ETHEREUM_MAINNET",
    "ETHEREUM_MAINNET_CHAIN_ID",
    "ETHEREUM_MAINNET_GENESIS_HASH",
    "EVM_NAMESPACE",
    "EthereumIdentityError",
    "EthereumLedgerProvider",
    "EvmBlockBundle",
    "EvmHead",
    "EvmNetwork",
    "JsonRpcTransport",
    "encode_quantity",
    "normalize_address",
    "normalize_hash",
    "parse_quantity",
]
