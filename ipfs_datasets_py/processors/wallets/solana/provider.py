"""Bounded, read-only Solana JSON-RPC provider."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
import json
from typing import Any, Protocol

from ..checkpoints import CheckpointIdentity, CheckpointRecord, build_checkpoint
from ..errors import (
    InvalidRequestError,
    ProviderError,
    ResourceLimitError,
)
from ..models import ChainRef
from ..protocols import (
    BoundedRequest,
    Capabilities,
    Capability,
    OperationContext,
    RecordBatch,
)
from .models import (
    Commitment,
    SOLANA_MAINNET,
    SOLANA_NAMESPACE,
    SolanaBlockBundle,
    SolanaHead,
    SolanaNetwork,
    SolanaSignatureInfo,
    SolanaTransactionBundle,
    normalize_pubkey,
    normalize_signature,
    parse_non_negative_int,
)


class SolanaJsonRpcTransport(Protocol):
    async def json_rpc(
        self,
        url: str,
        method: str,
        params: Mapping[str, object] | Sequence[object],
        *,
        context: OperationContext,
        request_id: int | str = 1,
        headers: Mapping[str, str] | None = None,
    ) -> object: ...


class SolanaIdentityError(ProviderError):
    """The configured endpoint is attached to a different genesis."""


class MissingSolanaSlotError(ProviderError):
    """A requested slot is skipped, missing, or unavailable at the commitment."""


class _RequestBudget:
    def __init__(self, context: OperationContext) -> None:
        self.context = context
        self.used = 0

    def consume(self) -> None:
        self.context.check_active()
        self.used += 1
        if self.used > self.context.limits.max_requests:
            raise ResourceLimitError("Solana JSON-RPC request budget exceeded")


def _commitment(value: object, *, default: Commitment) -> Commitment:
    if value is None:
        return default
    try:
        return Commitment(value)
    except (TypeError, ValueError):
        raise InvalidRequestError(
            "commitment must be processed, confirmed, or finalized"
        ) from None


def _mapping(value: object, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProviderError(f"{field_name} must be a mapping")
    return value


class SolanaLedgerProvider:
    """Dependency-light observation surface for accounts, signatures, and slots."""

    __slots__ = (
        "_endpoint",
        "_network",
        "_provider_name",
        "_transport",
        "_validated_chain",
    )

    def __init__(
        self,
        transport: SolanaJsonRpcTransport,
        *,
        endpoint: str,
        network: SolanaNetwork = SOLANA_MAINNET,
        provider_name: str = "solana-json-rpc",
    ) -> None:
        if not callable(getattr(transport, "json_rpc", None)):
            raise TypeError("transport must provide async json_rpc")
        if not isinstance(endpoint, str) or not endpoint.startswith(("http://", "https://")):
            raise InvalidRequestError("endpoint must be an HTTP(S) URL")
        if not isinstance(network, SolanaNetwork):
            raise InvalidRequestError("network must be a SolanaNetwork")
        if not isinstance(provider_name, str) or not provider_name.strip():
            raise InvalidRequestError("provider_name must not be empty")
        self._transport = transport
        self._endpoint = endpoint
        self._network = network
        self._provider_name = provider_name
        self._validated_chain: ChainRef | None = None

    def __repr__(self) -> str:
        return (
            f"SolanaLedgerProvider(provider_name={self._provider_name!r}, "
            f"network={self._network.network!r}, endpoint=<redacted>)"
        )

    @property
    def chain(self) -> ChainRef:
        return self._network.to_chain_ref()

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            provider=self._provider_name,
            chain_namespaces=frozenset({SOLANA_NAMESPACE}),
            features=frozenset(
                {
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
            ),
            metadata={
                "network": self._network.network,
                "chain_id": self._network.chain_id,
                "genesis_hash": self._network.genesis_hash,
                "commitments": tuple(item.value for item in Commitment),
                "versioned_transactions": True,
                "address_lookup_tables": True,
                "read_only": True,
                "supports_sign": False,
                "supports_submit": False,
                "supports_broadcast": False,
                "nft_enrichment": "optional_projection",
            },
        )

    async def _call(
        self,
        method: str,
        params: Sequence[object],
        *,
        context: OperationContext,
        budget: _RequestBudget,
    ) -> object:
        budget.consume()
        return await self._transport.json_rpc(
            self._endpoint,
            method,
            params,
            context=context,
            request_id=context.request_id,
        )

    async def _validate_identity(
        self, *, context: OperationContext, budget: _RequestBudget
    ) -> ChainRef:
        genesis = await self._call("getGenesisHash", (), context=context, budget=budget)
        if genesis != self._network.genesis_hash:
            raise SolanaIdentityError("provider genesis hash does not match configured cluster")
        self._validated_chain = self.chain
        return self._validated_chain

    async def validate_identity(self, *, context: OperationContext) -> ChainRef:
        return await self._validate_identity(
            context=context, budget=_RequestBudget(context)
        )

    async def _ensure_identity(
        self, *, context: OperationContext, budget: _RequestBudget
    ) -> ChainRef:
        if self._validated_chain is None:
            return await self._validate_identity(context=context, budget=budget)
        return self._validated_chain

    async def validate_address(
        self, address: str, *, context: OperationContext
    ) -> str:
        context.check_active()
        return normalize_pubkey(address, field_name="address")

    async def get_slot(
        self,
        commitment: Commitment,
        *,
        context: OperationContext,
        budget: _RequestBudget | None = None,
    ) -> int:
        own_budget = budget or _RequestBudget(context)
        result = await self._call(
            "getSlot",
            ({"commitment": commitment.value},),
            context=context,
            budget=own_budget,
        )
        return parse_non_negative_int(result, field_name=f"{commitment.value} slot")

    async def get_block(
        self,
        slot: int,
        *,
        commitment: Commitment,
        context: OperationContext,
        budget: _RequestBudget,
        transaction_details: str = "full",
    ) -> Mapping[str, Any]:
        slot = parse_non_negative_int(slot, field_name="slot")
        result = await self._call(
            "getBlock",
            (
                slot,
                {
                    "commitment": commitment.value,
                    "encoding": "jsonParsed",
                    "maxSupportedTransactionVersion": 0,
                    "rewards": False,
                    "transactionDetails": transaction_details,
                },
            ),
            context=context,
            budget=budget,
        )
        if result is None:
            raise MissingSolanaSlotError(
                f"Solana slot {slot} is skipped, missing, or unavailable; "
                "checkpoint was not advanced"
            )
        return _mapping(result, field_name=f"getBlock({slot})")

    async def get_transaction(
        self,
        signature: str,
        *,
        commitment: Commitment,
        context: OperationContext,
        budget: _RequestBudget,
    ) -> Mapping[str, Any]:
        signature = normalize_signature(signature)
        result = await self._call(
            "getTransaction",
            (
                signature,
                {
                    "commitment": commitment.value,
                    "encoding": "jsonParsed",
                    "maxSupportedTransactionVersion": 0,
                },
            ),
            context=context,
            budget=budget,
        )
        if result is None:
            raise ProviderError(
                f"transaction {signature} is unavailable at {commitment.value} commitment"
            )
        return _mapping(result, field_name="getTransaction")

    async def get_balance(
        self,
        address: str,
        *,
        commitment: Commitment = Commitment.FINALIZED,
        context: OperationContext,
    ) -> int:
        budget = _RequestBudget(context)
        await self._ensure_identity(context=context, budget=budget)
        address = await self.validate_address(address, context=context)
        result = _mapping(
            await self._call(
                "getBalance",
                (address, {"commitment": commitment.value}),
                context=context,
                budget=budget,
            ),
            field_name="getBalance",
        )
        return parse_non_negative_int(result.get("value"), field_name="balance lamports")

    async def ledger_head(self, *, context: OperationContext) -> SolanaHead:
        """Return all commitment heads plus a finalized slot/blockhash anchor."""

        budget = _RequestBudget(context)
        await self._ensure_identity(context=context, budget=budget)
        processed = await self.get_slot(
            Commitment.PROCESSED, context=context, budget=budget
        )
        confirmed = await self.get_slot(
            Commitment.CONFIRMED, context=context, budget=budget
        )
        finalized = await self.get_slot(
            Commitment.FINALIZED, context=context, budget=budget
        )
        if not processed >= confirmed >= finalized:
            raise ProviderError("Solana commitment slot ordering is inconsistent")
        block = await self.get_block(
            finalized,
            commitment=Commitment.FINALIZED,
            context=context,
            budget=budget,
            transaction_details="none",
        )
        blockhash = block.get("blockhash")
        if not isinstance(blockhash, str) or not blockhash:
            raise ProviderError("finalized block response is missing blockhash")
        return SolanaHead(processed, confirmed, finalized, blockhash)

    async def finalized_checkpoint(
        self,
        scope: str,
        *,
        context: OperationContext,
        continuation_token: str | None = None,
    ) -> CheckpointRecord:
        """Build a checkpoint only from the finalized slot/blockhash pair."""

        if not isinstance(scope, str) or not scope.strip():
            raise InvalidRequestError("checkpoint scope must not be empty")
        head = await self.ledger_head(context=context)
        identity = CheckpointIdentity(
            chain=self.chain,
            provider=self._provider_name,
            scope=scope,
            normalized_schema_major=1,
            normalizer_version="solana-normalizer-v1",
        )
        return build_checkpoint(
            identity,
            sequence=head.finalized_slot,
            block_hash=head.finalized_blockhash,
            continuation_token=continuation_token,
            metadata={"commitment": Commitment.FINALIZED.value},
        )

    @staticmethod
    def _signature_info(
        value: object, *, default_commitment: Commitment
    ) -> SolanaSignatureInfo:
        item = _mapping(value, field_name="signature entry")
        status = item.get("confirmationStatus")
        if status is None:
            # Historical responses may omit the field; retain the exact
            # commitment requested instead of silently upgrading finality.
            status = default_commitment.value
        return SolanaSignatureInfo(
            signature=item.get("signature"),
            slot=item.get("slot"),
            err=item.get("err"),
            memo=item.get("memo"),
            block_time=item.get("blockTime"),
            confirmation_status=Commitment(status),
        )

    async def _signature_page(
        self,
        address: str,
        *,
        before: str | None,
        limit: int,
        commitment: Commitment,
        context: OperationContext,
        budget: _RequestBudget,
    ) -> tuple[SolanaSignatureInfo, ...]:
        config: dict[str, object] = {
            "commitment": commitment.value,
            "limit": limit,
        }
        if before is not None:
            config["before"] = normalize_signature(before, field_name="before cursor")
        result = await self._call(
            "getSignaturesForAddress",
            (address, config),
            context=context,
            budget=budget,
        )
        if not isinstance(result, Sequence) or isinstance(result, (str, bytes)):
            raise ProviderError("getSignaturesForAddress must return a sequence")
        return tuple(
            self._signature_info(item, default_commitment=commitment)
            for item in result
        )

    @staticmethod
    def _transaction_bundle(
        result: Mapping[str, Any],
        *,
        fallback_slot: int,
        fallback_block_time: int | None,
        blockhash: str,
        commitment: Commitment,
    ) -> SolanaTransactionBundle:
        transaction = result.get("transaction")
        if not isinstance(transaction, Mapping):
            raise ProviderError("getTransaction response is missing transaction")
        meta = result.get("meta")
        if not isinstance(meta, Mapping):
            raise ProviderError("getTransaction response is missing meta")
        wrapped = {"transaction": transaction, "meta": meta, "version": result.get("version")}
        slot = parse_non_negative_int(
            result.get("slot", fallback_slot), field_name="transaction slot"
        )
        if not isinstance(blockhash, str) or not blockhash:
            raise ProviderError("containing slot is missing its canonical blockhash")
        return SolanaTransactionBundle(
            transaction=wrapped,
            slot=slot,
            blockhash=blockhash,
            block_time=result.get("blockTime", fallback_block_time),
            commitment=commitment,
        )

    async def ingest_wallet(
        self, request: BoundedRequest
    ) -> AsyncIterator[RecordBatch]:
        """Paginate signatures without gaps/duplicates, then fetch every tx."""

        context = request.context
        context.check_active()
        address = normalize_pubkey(request.scope, field_name="scope")
        commitment = _commitment(
            request.options.get("commitment"), default=Commitment.FINALIZED
        )
        page_size_value = request.options.get(
            "page_size", min(1_000, context.limits.max_items)
        )
        page_size = parse_non_negative_int(page_size_value, field_name="page_size")
        if page_size == 0 or page_size > 1_000:
            raise InvalidRequestError("page_size must be between 1 and 1000")
        budget = _RequestBudget(context)
        await self._ensure_identity(context=context, budget=budget)
        before = request.cursor
        seen_cursors: set[str] = set()
        seen_signatures: set[str] = set()
        slot_anchors: dict[int, str] = {}
        item_count = 0

        for _page_index in range(context.limits.max_pages):
            if before is not None:
                if before in seen_cursors:
                    raise ProviderError(f"Solana signature pagination cursor loop at {before!r}")
                seen_cursors.add(before)
            page = await self._signature_page(
                address,
                before=before,
                limit=page_size,
                commitment=commitment,
                context=context,
                budget=budget,
            )
            if not page:
                return
            unique_page: list[SolanaSignatureInfo] = []
            for info in page:
                if info.signature in seen_signatures:
                    continue
                seen_signatures.add(info.signature)
                unique_page.append(info)
            item_count += len(unique_page)
            if item_count > context.limits.max_items:
                raise ResourceLimitError("Solana wallet history exceeds max_items")
            bundles: list[SolanaTransactionBundle] = []
            for info in unique_page:
                result = await self.get_transaction(
                    info.signature,
                    commitment=commitment,
                    context=context,
                    budget=budget,
                )
                slot = parse_non_negative_int(
                    result.get("slot", info.slot), field_name="transaction slot"
                )
                if slot not in slot_anchors:
                    containing_block = await self.get_block(
                        slot,
                        commitment=commitment,
                        context=context,
                        budget=budget,
                        transaction_details="none",
                    )
                    blockhash = containing_block.get("blockhash")
                    if not isinstance(blockhash, str) or not blockhash:
                        raise ProviderError(
                            f"Solana slot {slot} is missing canonical blockhash"
                        )
                    slot_anchors[slot] = blockhash
                bundles.append(
                    self._transaction_bundle(
                        result,
                        fallback_slot=info.slot,
                        fallback_block_time=info.block_time,
                        blockhash=slot_anchors[slot],
                        commitment=info.confirmation_status,
                    )
                )
            next_cursor = page[-1].signature if len(page) == page_size else None
            response_bytes = len(
                json.dumps(
                    [dict(bundle.transaction) for bundle in bundles],
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            batch = RecordBatch(
                records=tuple(bundles),
                next_cursor=next_cursor,
                response_bytes=response_bytes,
            )
            batch.enforce(context.limits)
            if bundles:
                yield batch
            if next_cursor is None:
                return
            if next_cursor == before:
                raise ProviderError("Solana signature pagination did not advance")
            before = next_cursor
        raise ResourceLimitError("Solana signature pagination exceeds max_pages")

    async def ingest_ledger(
        self, request: BoundedRequest
    ) -> AsyncIterator[RecordBatch]:
        """Stream an inclusive finite slot range; missing slots fail closed."""

        context = request.context
        context.check_active()
        if request.start_position is None or request.end_position is None:
            raise InvalidRequestError(
                "Solana ledger ingestion requires start_position and end_position"
            )
        count = request.end_position - request.start_position + 1
        if count > context.limits.max_pages:
            raise ResourceLimitError("Solana slot range exceeds max_pages")
        commitment = _commitment(
            request.options.get("commitment"), default=Commitment.FINALIZED
        )
        budget = _RequestBudget(context)
        await self._ensure_identity(context=context, budget=budget)
        for slot in range(request.start_position, request.end_position + 1):
            result = await self.get_block(
                slot,
                commitment=commitment,
                context=context,
                budget=budget,
            )
            blockhash = result.get("blockhash")
            if not isinstance(blockhash, str) or not blockhash:
                raise ProviderError(f"Solana slot {slot} is missing blockhash")
            transactions = result.get("transactions")
            if not isinstance(transactions, Sequence) or isinstance(
                transactions, (str, bytes)
            ):
                raise ProviderError("Solana block transactions must be a sequence")
            if len(transactions) > context.limits.max_items:
                raise ResourceLimitError("Solana block exceeds max_items")
            bundles = tuple(
                SolanaTransactionBundle(
                    transaction=_mapping(value, field_name="block transaction"),
                    slot=slot,
                    blockhash=blockhash,
                    block_time=result.get("blockTime"),
                    commitment=commitment,
                    transaction_index=index,
                )
                for index, value in enumerate(transactions)
            )
            block = SolanaBlockBundle(
                slot=slot,
                blockhash=blockhash,
                previous_blockhash=result.get("previousBlockhash"),
                parent_slot=parse_non_negative_int(
                    result.get("parentSlot"), field_name="parentSlot"
                ),
                block_time=result.get("blockTime"),
                transactions=bundles,
                commitment=commitment,
            )
            response_bytes = len(
                json.dumps(result, separators=(",", ":")).encode("utf-8")
            )
            batch = RecordBatch(records=(block,), response_bytes=response_bytes)
            batch.enforce(context.limits)
            yield batch


__all__ = [
    "MissingSolanaSlotError",
    "SolanaIdentityError",
    "SolanaJsonRpcTransport",
    "SolanaLedgerProvider",
]
