"""Pure Ethereum block, transaction, receipt, log, and trace normalization."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..canonical import content_digest
from ..errors import NormalizationError, ResourceLimitError
from ..models import (
    AccountKind,
    AccountRef,
    AssetKind,
    AssetRef,
    BlockRecord,
    ContractEventRecord,
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
from .rpc import (
    EVM_NAMESPACE,
    EvmBlockBundle,
    EvmNetwork,
    normalize_address,
    normalize_hash,
    parse_quantity,
)


ETHEREUM_EXTENSION_VERSION = "wallet-ethereum-v1"
TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)
ERC1155_TRANSFER_SINGLE_TOPIC = (
    "0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62"
)
ERC1155_TRANSFER_BATCH_TOPIC = (
    "0x4a39dc06d4c0dbc64b70af90fd698a233a518aa5d07e595d983b8c0526c8f7fb"
)
ZERO_ADDRESS = "0x" + "00" * 20


def _hex_data(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise NormalizationError(f"{field} must be 0x-prefixed hex data")
    payload = value[2:]
    if len(payload) % 2:
        raise NormalizationError(f"{field} must contain whole bytes")
    try:
        bytes.fromhex(payload)
    except ValueError:
        raise NormalizationError(f"{field} contains invalid hex") from None
    return value.lower()


def _word(value: str, index: int, *, field: str = "data") -> int:
    payload = _hex_data(value, field=field)[2:]
    start = index * 64
    word = payload[start : start + 64]
    if len(word) != 64:
        raise NormalizationError(f"{field} is missing ABI word {index}")
    return int(word, 16)


def _topic_address(topic: object, *, field: str) -> str:
    normalized = normalize_hash(topic, field=field)
    return normalize_address("0x" + normalized[-40:], field=field)


def _pair_index(left: int, right: int) -> int:
    total = left + right
    return total * (total + 1) // 2 + right


def _token_transfer_index(log_index: int, item_index: int) -> int:
    # Residue 1 is reserved for log transfers. Native is 0; traces use 2 mod 3.
    return 1 + 3 * _pair_index(log_index, item_index)


@dataclass(frozen=True, slots=True)
class TokenMetadata:
    """Optional caller-supplied token display metadata."""

    decimals: int
    symbol: str | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.decimals, bool)
            or not isinstance(self.decimals, int)
            or not 0 <= self.decimals <= 255
        ):
            raise NormalizationError("token decimals must be between 0 and 255")


@dataclass(frozen=True, slots=True)
class DecodedTokenTransfer:
    standard: str
    contract: str
    source: str
    destination: str
    value: int
    token_id: int | None
    operator: str | None
    log_index: int
    item_index: int = 0
    removed: bool = False


def _decode_uint_array(data: str, offset: int, *, field: str) -> tuple[int, ...]:
    payload = _hex_data(data, field=field)[2:]
    if offset % 32 or offset < 0:
        raise NormalizationError(f"{field} ABI offset is invalid")
    start = offset * 2
    if start + 64 > len(payload):
        raise NormalizationError(f"{field} ABI offset is out of range")
    count = int(payload[start : start + 64], 16)
    if count > 10_000:
        raise ResourceLimitError(f"{field} array exceeds 10000 items")
    cursor = start + 64
    end = cursor + count * 64
    if end > len(payload):
        raise NormalizationError(f"{field} ABI array is truncated")
    return tuple(
        int(payload[cursor + index * 64 : cursor + (index + 1) * 64], 16)
        for index in range(count)
    )


def decode_transfer_log(log: Mapping[str, Any]) -> tuple[DecodedTokenTransfer, ...]:
    """Decode ERC-20, ERC-721, and ERC-1155 transfer logs.

    Unknown signatures are not errors. Recognized-but-malformed logs fail
    closed so data corruption is never silently projected as a transfer.
    """

    topics = log.get("topics")
    if not isinstance(topics, Sequence) or isinstance(topics, (str, bytes)):
        raise NormalizationError("log.topics must be a sequence")
    if not topics:
        return ()
    signature = normalize_hash(topics[0], field="log.topics[0]")
    if signature not in {
        TRANSFER_TOPIC,
        ERC1155_TRANSFER_SINGLE_TOPIC,
        ERC1155_TRANSFER_BATCH_TOPIC,
    }:
        return ()
    contract = normalize_address(log.get("address"), field="log.address")
    log_index = parse_quantity(log.get("logIndex"), field="log.logIndex")
    removed = bool(log.get("removed", False))
    data = _hex_data(log.get("data", "0x"), field="log.data")

    if signature == TRANSFER_TOPIC:
        if len(topics) == 3:
            return (
                DecodedTokenTransfer(
                    standard="erc20",
                    contract=contract,
                    source=_topic_address(topics[1], field="log.topics[1]"),
                    destination=_topic_address(topics[2], field="log.topics[2]"),
                    value=_word(data, 0, field="log.data"),
                    token_id=None,
                    operator=None,
                    log_index=log_index,
                    removed=removed,
                ),
            )
        if len(topics) == 4:
            token_topic = normalize_hash(topics[3], field="log.topics[3]")
            return (
                DecodedTokenTransfer(
                    standard="erc721",
                    contract=contract,
                    source=_topic_address(topics[1], field="log.topics[1]"),
                    destination=_topic_address(topics[2], field="log.topics[2]"),
                    value=1,
                    token_id=int(token_topic[2:], 16),
                    operator=None,
                    log_index=log_index,
                    removed=removed,
                ),
            )
        raise NormalizationError("Transfer log must have three or four topics")

    if len(topics) != 4:
        raise NormalizationError("ERC-1155 transfer log must have four topics")
    operator = _topic_address(topics[1], field="log.topics[1]")
    source = _topic_address(topics[2], field="log.topics[2]")
    destination = _topic_address(topics[3], field="log.topics[3]")
    if signature == ERC1155_TRANSFER_SINGLE_TOPIC:
        return (
            DecodedTokenTransfer(
                standard="erc1155",
                contract=contract,
                source=source,
                destination=destination,
                token_id=_word(data, 0, field="log.data"),
                value=_word(data, 1, field="log.data"),
                operator=operator,
                log_index=log_index,
                removed=removed,
            ),
        )

    ids_offset = _word(data, 0, field="log.data")
    values_offset = _word(data, 1, field="log.data")
    ids = _decode_uint_array(data, ids_offset, field="log.data.ids")
    values = _decode_uint_array(data, values_offset, field="log.data.values")
    if len(ids) != len(values):
        raise NormalizationError("ERC-1155 batch ids/values length mismatch")
    return tuple(
        DecodedTokenTransfer(
            standard="erc1155",
            contract=contract,
            source=source,
            destination=destination,
            token_id=token_id,
            value=values[index],
            operator=operator,
            log_index=log_index,
            item_index=index,
            removed=removed,
        )
        for index, token_id in enumerate(ids)
    )


class EthereumNormalizer:
    """Convert raw EVM bundles into immutable shared wallet records."""

    __slots__ = ("_clock", "_network", "_provider", "_token_metadata")
    normalizer_version = "ethereum-normalizer-v1"

    def __init__(
        self,
        network: EvmNetwork,
        *,
        provider: str = "ethereum-json-rpc",
        token_metadata: Mapping[str, TokenMetadata] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if not isinstance(network, EvmNetwork):
            raise NormalizationError("network must be an EvmNetwork")
        self._network = network
        self._provider = provider
        self._token_metadata = {
            normalize_address(key): value
            for key, value in (token_metadata or {}).items()
        }
        if any(not isinstance(value, TokenMetadata) for value in self._token_metadata.values()):
            raise NormalizationError("token_metadata values must be TokenMetadata")
        self._clock = clock

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            provider=f"{self._provider}-normalizer",
            chain_namespaces=frozenset({EVM_NAMESPACE}),
            features=frozenset(
                {
                    Capability.LEDGER_RANGE,
                    Capability.WALLET_HISTORY,
                    Capability.TOKEN_TRANSFERS,
                    Capability.CONTRACT_EVENTS,
                    Capability.INTERNAL_TRANSFERS,
                    Capability.RAW_PAYLOADS,
                    Capability.DATASET_EXPORT,
                }
            ),
            metadata={
                "normalizer_version": self.normalizer_version,
                "token_metadata_required": False,
                "read_only": True,
            },
        )

    def _provenance(
        self,
        payload: object,
        *,
        context: OperationContext,
        scope: str,
    ) -> Provenance:
        observed_at = self._clock()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise NormalizationError("normalizer clock must be timezone-aware")
        return Provenance(
            provider=self._provider,
            provider_kind="ethereum-json-rpc",
            request_id=context.request_id,
            scope=scope,
            observed_at=observed_at,
            raw_payload=RawPayloadRef(digest=content_digest(payload)),
        )

    @staticmethod
    def _extension(data: Mapping[str, Any]) -> Mapping[str, VersionedExtension]:
        return {
            "ethereum": VersionedExtension(
                schema_version=ETHEREUM_EXTENSION_VERSION,
                data=data,
            )
        }

    def normalize(
        self,
        records: Sequence[object],
        *,
        context: OperationContext,
    ) -> tuple[object, ...]:
        context.check_active()
        output: list[object] = []
        for record in records:
            if not isinstance(record, EvmBlockBundle):
                raise NormalizationError("Ethereum normalizer expects EvmBlockBundle")
            output.extend(self.normalize_bundle(record, context=context))
            if len(output) > context.limits.max_items:
                raise ResourceLimitError("normalized Ethereum records exceed max_items")
        return tuple(output)

    def normalize_bundle(
        self,
        bundle: EvmBlockBundle,
        *,
        context: OperationContext,
    ) -> tuple[object, ...]:
        block = bundle.block
        chain = self._network.to_chain_ref()
        block_hash = normalize_hash(block.get("hash"), field="block.hash")
        block_number = parse_quantity(block.get("number"), field="block.number")
        parent_hash = normalize_hash(block.get("parentHash"), field="block.parentHash")
        timestamp = datetime.fromtimestamp(
            parse_quantity(block.get("timestamp"), field="block.timestamp"),
            tz=timezone.utc,
        )
        transactions = block.get("transactions")
        if not isinstance(transactions, Sequence) or isinstance(
            transactions, (str, bytes)
        ):
            raise NormalizationError("block.transactions must be a sequence")
        receipts_by_hash = {
            normalize_hash(receipt.get("transactionHash"), field="receipt.transactionHash"): receipt
            for receipt in bundle.receipts
        }
        block_position = LedgerPosition(sequence=block_number, hash=block_hash)
        output: list[object] = [
            BlockRecord(
                chain=chain,
                provenance=self._provenance(block, context=context, scope="ledger"),
                ledger_position=block_position,
                finality=Finality.OBSERVED,
                block_hash=block_hash,
                parent_hash=parent_hash,
                block_time=timestamp,
                transaction_count=len(transactions),
                extensions=self._extension(
                    {
                        "base_fee_per_gas": (
                            None
                            if block.get("baseFeePerGas") is None
                            else str(parse_quantity(block["baseFeePerGas"], field="block.baseFeePerGas"))
                        )
                    }
                ),
            )
        ]
        for fallback_index, transaction in enumerate(transactions):
            if not isinstance(transaction, Mapping):
                raise NormalizationError("block transaction must be a mapping")
            tx_hash = normalize_hash(transaction.get("hash"), field="transaction.hash")
            receipt = receipts_by_hash.get(tx_hash)
            if receipt is None:
                raise NormalizationError(f"receipt missing for transaction {tx_hash}")
            output.extend(
                self._normalize_transaction(
                    transaction,
                    receipt,
                    block_hash=block_hash,
                    block_number=block_number,
                    block_time=timestamp,
                    trace=bundle.traces.get(tx_hash),
                    trace_capability=bundle.trace_capability,
                    fallback_index=fallback_index,
                    context=context,
                )
            )
        return tuple(output)

    def _account(
        self,
        address: object,
        *,
        kind: AccountKind = AccountKind.ADDRESS,
    ) -> AccountRef:
        return AccountRef(self._network.to_chain_ref(), normalize_address(address), kind)

    def _native_asset(self) -> AssetRef:
        return AssetRef(
            chain=self._network.to_chain_ref(),
            asset_namespace="slip44",
            asset_reference="60",
            decimals=self._network.native_decimals,
            kind=AssetKind.NATIVE,
            symbol=self._network.native_symbol,
        )

    def _normalize_transaction(
        self,
        transaction: Mapping[str, Any],
        receipt: Mapping[str, Any],
        *,
        block_hash: str,
        block_number: int,
        block_time: datetime,
        trace: tuple[Mapping[str, Any], ...] | None,
        trace_capability: bool,
        fallback_index: int,
        context: OperationContext,
    ) -> tuple[object, ...]:
        tx_hash = normalize_hash(transaction.get("hash"), field="transaction.hash")
        receipt_hash = normalize_hash(
            receipt.get("transactionHash"), field="receipt.transactionHash"
        )
        if receipt_hash != tx_hash:
            raise NormalizationError("receipt transaction hash does not match")
        receipt_block_hash = normalize_hash(
            receipt.get("blockHash"), field="receipt.blockHash"
        )
        if receipt_block_hash != block_hash:
            raise NormalizationError("receipt block hash does not match block")
        tx_index = parse_quantity(
            transaction.get("transactionIndex", hex(fallback_index)),
            field="transaction.transactionIndex",
        )
        position = LedgerPosition(
            sequence=block_number,
            hash=block_hash,
            transaction_index=tx_index,
        )
        source = self._account(transaction.get("from"))
        contract_address = receipt.get("contractAddress")
        destination = (
            self._account(contract_address, kind=AccountKind.CONTRACT)
            if transaction.get("to") is None and contract_address
            else self._account(transaction.get("to"))
            if transaction.get("to") is not None
            else None
        )
        participants = (source,) if destination is None else (source, destination)
        status_value = parse_quantity(receipt.get("status", "0x0"), field="receipt.status")
        status = (
            TransactionStatus.SUCCEEDED
            if status_value == 1
            else TransactionStatus.FAILED
        )
        gas_used = parse_quantity(receipt.get("gasUsed"), field="receipt.gasUsed")
        gas_price_raw = receipt.get("effectiveGasPrice", transaction.get("gasPrice"))
        gas_price = parse_quantity(gas_price_raw, field="receipt.effectiveGasPrice")
        fee = gas_used * gas_price
        tx_type = parse_quantity(transaction.get("type", "0x0"), field="transaction.type")
        extensions = self._extension(
            {
                "transaction_type": tx_type,
                "nonce": str(parse_quantity(transaction.get("nonce"), field="transaction.nonce")),
                "gas_limit": str(parse_quantity(transaction.get("gas"), field="transaction.gas")),
                "gas_used": str(gas_used),
                "effective_gas_price": str(gas_price),
                "legacy_gas_price": (
                    None
                    if transaction.get("gasPrice") is None
                    else str(parse_quantity(transaction["gasPrice"], field="transaction.gasPrice"))
                ),
                "max_fee_per_gas": (
                    None
                    if transaction.get("maxFeePerGas") is None
                    else str(parse_quantity(transaction["maxFeePerGas"], field="transaction.maxFeePerGas"))
                ),
                "max_priority_fee_per_gas": (
                    None
                    if transaction.get("maxPriorityFeePerGas") is None
                    else str(parse_quantity(transaction["maxPriorityFeePerGas"], field="transaction.maxPriorityFeePerGas"))
                ),
                "contract_creation": transaction.get("to") is None,
                "contract_address": (
                    None
                    if contract_address is None
                    else normalize_address(contract_address)
                ),
                "receipt_status": status_value,
                "trace_capability": trace_capability,
                "internal_value_available": trace is not None,
                "internal_value_complete": trace is not None,
            }
        )
        output: list[object] = [
            TransactionRecord(
                chain=self._network.to_chain_ref(),
                provenance=self._provenance(
                    {"transaction": transaction, "receipt": receipt},
                    context=context,
                    scope="ledger",
                ),
                ledger_position=position,
                finality=Finality.REVERTED if status is TransactionStatus.FAILED else Finality.OBSERVED,
                transaction_hash=tx_hash,
                status=status,
                participants=participants,
                fee=ExactAmount.from_int(fee, decimals=self._network.native_decimals),
                block_time=block_time,
                extensions=extensions,
            )
        ]

        value = parse_quantity(transaction.get("value", "0x0"), field="transaction.value")
        if value > 0:
            output.append(
                TransferRecord(
                    chain=self._network.to_chain_ref(),
                    provenance=self._provenance(
                        transaction, context=context, scope="ledger"
                    ),
                    ledger_position=position,
                    finality=(
                        Finality.REVERTED
                        if status is TransactionStatus.FAILED
                        else Finality.OBSERVED
                    ),
                    transaction_hash=tx_hash,
                    transfer_index=0,
                    asset=self._native_asset(),
                    amount=ExactAmount.from_int(
                        value, decimals=self._network.native_decimals
                    ),
                    source_account=source,
                    destination_account=destination,
                    transfer_kind=TransferKind.NATIVE,
                    extensions=self._extension(
                        {
                            "execution_status": status.value,
                            "contract_creation": transaction.get("to") is None,
                        }
                    ),
                )
            )

        logs = receipt.get("logs", ())
        if not isinstance(logs, Sequence) or isinstance(logs, (str, bytes)):
            raise NormalizationError("receipt.logs must be a sequence")
        for log in logs:
            if not isinstance(log, Mapping):
                raise NormalizationError("receipt log must be a mapping")
            output.extend(
                self._normalize_log(
                    log,
                    transaction_hash=tx_hash,
                    block_hash=block_hash,
                    block_number=block_number,
                    transaction_index=tx_index,
                    context=context,
                )
            )

        if trace is not None:
            output.extend(
                self._normalize_traces(
                    trace,
                    transaction_hash=tx_hash,
                    block_hash=block_hash,
                    block_number=block_number,
                    transaction_index=tx_index,
                    context=context,
                )
            )
        return tuple(output)

    def _normalize_log(
        self,
        log: Mapping[str, Any],
        *,
        transaction_hash: str,
        block_hash: str,
        block_number: int,
        transaction_index: int,
        context: OperationContext,
    ) -> tuple[object, ...]:
        log_tx_hash = normalize_hash(
            log.get("transactionHash"), field="log.transactionHash"
        )
        if log_tx_hash != transaction_hash:
            raise NormalizationError("log transaction hash does not match receipt")
        log_index = parse_quantity(log.get("logIndex"), field="log.logIndex")
        removed = bool(log.get("removed", False))
        topics = log.get("topics")
        if not isinstance(topics, Sequence) or isinstance(topics, (str, bytes)):
            raise NormalizationError("log.topics must be a sequence")
        normalized_topics = tuple(
            normalize_hash(topic, field="log.topic") for topic in topics
        )
        finality = Finality.ORPHANED if removed else Finality.OBSERVED
        position = LedgerPosition(
            sequence=block_number,
            hash=block_hash,
            transaction_index=transaction_index,
            event_index=log_index,
        )
        contract = self._account(log.get("address"), kind=AccountKind.CONTRACT)
        output: list[object] = [
            ContractEventRecord(
                chain=self._network.to_chain_ref(),
                provenance=self._provenance(log, context=context, scope="ledger"),
                ledger_position=position,
                finality=finality,
                transaction_hash=transaction_hash,
                event_index=log_index,
                contract=contract,
                event_signature=normalized_topics[0] if normalized_topics else None,
                topics=normalized_topics,
                data_ref=RawPayloadRef(digest=content_digest(log.get("data", "0x"))),
                extensions=self._extension(
                    {
                        "removed": removed,
                        "raw_log_digest": content_digest(log),
                    }
                ),
            )
        ]
        for decoded in decode_transfer_log(log):
            metadata = self._token_metadata.get(decoded.contract)
            if decoded.standard == "erc20":
                decimals = metadata.decimals if metadata is not None else 0
                kind = AssetKind.FUNGIBLE_TOKEN
                asset_reference = decoded.contract
                symbol = metadata.symbol if metadata is not None else None
            elif decoded.standard == "erc721":
                decimals = 0
                kind = AssetKind.NON_FUNGIBLE_TOKEN
                asset_reference = f"{decoded.contract}/token/{decoded.token_id}"
                symbol = metadata.symbol if metadata is not None else None
            else:
                decimals = 0
                kind = AssetKind.MULTI_TOKEN
                asset_reference = f"{decoded.contract}/token/{decoded.token_id}"
                symbol = metadata.symbol if metadata is not None else None
            asset = AssetRef(
                chain=self._network.to_chain_ref(),
                asset_namespace=decoded.standard,
                asset_reference=asset_reference,
                decimals=decimals,
                kind=kind,
                symbol=symbol,
            )
            source = (
                None
                if decoded.source == ZERO_ADDRESS
                else self._account(decoded.source)
            )
            destination = (
                None
                if decoded.destination == ZERO_ADDRESS
                else self._account(decoded.destination)
            )
            transfer_kind = (
                TransferKind.MINT
                if source is None
                else TransferKind.BURN
                if destination is None
                else TransferKind.TOKEN
            )
            output.append(
                TransferRecord(
                    chain=self._network.to_chain_ref(),
                    provenance=self._provenance(
                        log, context=context, scope="ledger"
                    ),
                    ledger_position=position,
                    finality=Finality.ORPHANED if decoded.removed else Finality.OBSERVED,
                    transaction_hash=transaction_hash,
                    transfer_index=_token_transfer_index(
                        decoded.log_index, decoded.item_index
                    ),
                    asset=asset,
                    amount=ExactAmount.from_int(decoded.value, decimals=decimals),
                    source_account=source,
                    destination_account=destination,
                    transfer_kind=transfer_kind,
                    extensions=self._extension(
                        {
                            "standard": decoded.standard,
                            "token_id": (
                                None
                                if decoded.token_id is None
                                else str(decoded.token_id)
                            ),
                            "operator": decoded.operator,
                            "removed": decoded.removed,
                            "log_index": decoded.log_index,
                            "batch_item_index": decoded.item_index,
                            "token_metadata_complete": (
                                metadata is not None
                                or decoded.standard != "erc20"
                            ),
                            "base_units_exact": True,
                        }
                    ),
                )
            )
        return tuple(output)

    def _normalize_traces(
        self,
        traces: Sequence[Mapping[str, Any]],
        *,
        transaction_hash: str,
        block_hash: str,
        block_number: int,
        transaction_index: int,
        context: OperationContext,
    ) -> tuple[TransferRecord, ...]:
        output: list[TransferRecord] = []
        for trace_index, trace in enumerate(traces):
            if trace.get("error"):
                continue
            action = trace.get("action")
            if not isinstance(action, Mapping):
                continue
            value = parse_quantity(action.get("value", "0x0"), field="trace.action.value")
            if value == 0 or action.get("from") is None or action.get("to") is None:
                continue
            output.append(
                TransferRecord(
                    chain=self._network.to_chain_ref(),
                    provenance=self._provenance(
                        trace, context=context, scope="ledger"
                    ),
                    ledger_position=LedgerPosition(
                        sequence=block_number,
                        hash=block_hash,
                        transaction_index=transaction_index,
                    ),
                    finality=Finality.OBSERVED,
                    transaction_hash=transaction_hash,
                    transfer_index=2 + 3 * trace_index,
                    asset=self._native_asset(),
                    amount=ExactAmount.from_int(
                        value, decimals=self._network.native_decimals
                    ),
                    source_account=self._account(action["from"]),
                    destination_account=self._account(action["to"]),
                    transfer_kind=TransferKind.NATIVE,
                    extensions=self._extension(
                        {
                            "internal": True,
                            "trace_index": trace_index,
                            "trace_type": str(trace.get("type") or "call"),
                            "trace_complete": True,
                        }
                    ),
                )
            )
        return tuple(output)


__all__ = [
    "DecodedTokenTransfer",
    "ERC1155_TRANSFER_BATCH_TOPIC",
    "ERC1155_TRANSFER_SINGLE_TOPIC",
    "ETHEREUM_EXTENSION_VERSION",
    "EthereumNormalizer",
    "TRANSFER_TOPIC",
    "TokenMetadata",
    "ZERO_ADDRESS",
    "decode_transfer_log",
]
