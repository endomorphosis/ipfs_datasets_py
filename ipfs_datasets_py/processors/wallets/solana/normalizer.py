"""Pure Solana transaction, instruction, balance, and token normalization."""

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
    BalanceSnapshot,
    BlockRecord,
    ContractEventRecord,
    ExactAmount,
    LedgerPosition,
    Provenance,
    RawPayloadRef,
    TokenAccountRecord,
    TransactionRecord,
    TransactionStatus,
    TransferKind,
    TransferRecord,
    VersionedExtension,
)
from ..protocols import Capabilities, Capability, OperationContext
from .finality import SolanaFinalityPolicy
from .models import (
    Commitment,
    SOLANA_NAMESPACE,
    SolanaBlockBundle,
    SolanaNetwork,
    SolanaTransactionBundle,
    normalize_pubkey,
    normalize_signature,
    parse_non_negative_int,
    resolve_message_account_keys,
)


SOLANA_EXTENSION_VERSION = "wallet-solana-v1"
SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"
TOKEN_PROGRAM_IDS = frozenset(
    {
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
    }
)


@dataclass(frozen=True, slots=True)
class TokenMetadata:
    """Optional display/NFT projection metadata supplied outside ingestion."""

    decimals: int
    symbol: str | None = None
    kind: AssetKind = AssetKind.FUNGIBLE_TOKEN

    def __post_init__(self) -> None:
        if (
            isinstance(self.decimals, bool)
            or not isinstance(self.decimals, int)
            or not 0 <= self.decimals <= 255
        ):
            raise NormalizationError("token decimals must be between 0 and 255")
        if not isinstance(self.kind, AssetKind) or self.kind not in {
            AssetKind.FUNGIBLE_TOKEN,
            AssetKind.NON_FUNGIBLE_TOKEN,
            AssetKind.MULTI_TOKEN,
        }:
            raise NormalizationError("token metadata kind must be a token asset kind")


@dataclass(frozen=True, slots=True)
class _Instruction:
    value: Mapping[str, Any]
    outer_index: int
    inner_index: int | None
    event_index: int


class SolanaNormalizer:
    """Convert Solana RPC bundles into immutable shared wallet records."""

    __slots__ = (
        "_clock",
        "_include_program_logs",
        "_max_log_bytes",
        "_max_program_logs",
        "_network",
        "_provider",
        "_token_metadata",
    )
    normalizer_version = "solana-normalizer-v1"

    def __init__(
        self,
        network: SolanaNetwork,
        *,
        provider: str = "solana-json-rpc",
        token_metadata: Mapping[str, TokenMetadata] | None = None,
        include_program_logs: bool = False,
        max_program_logs: int = 1_000,
        max_log_bytes: int = 64 * 1024,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if not isinstance(network, SolanaNetwork):
            raise NormalizationError("network must be a SolanaNetwork")
        if (
            isinstance(max_program_logs, bool)
            or not isinstance(max_program_logs, int)
            or max_program_logs <= 0
            or isinstance(max_log_bytes, bool)
            or not isinstance(max_log_bytes, int)
            or max_log_bytes <= 0
        ):
            raise NormalizationError("program-log bounds must be positive integers")
        metadata: dict[str, TokenMetadata] = {}
        for mint, value in (token_metadata or {}).items():
            normalized_mint = normalize_pubkey(mint, field_name="token metadata mint")
            if not isinstance(value, TokenMetadata):
                raise NormalizationError("token_metadata values must be TokenMetadata")
            metadata[normalized_mint] = value
        self._network = network
        self._provider = provider
        self._token_metadata = metadata
        self._include_program_logs = bool(include_program_logs)
        self._max_program_logs = max_program_logs
        self._max_log_bytes = max_log_bytes
        self._clock = clock

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            provider=f"{self._provider}-normalizer",
            chain_namespaces=frozenset({SOLANA_NAMESPACE}),
            features=frozenset(
                {
                    Capability.LEDGER_RANGE,
                    Capability.WALLET_HISTORY,
                    Capability.BALANCES,
                    Capability.TOKEN_TRANSFERS,
                    Capability.CONTRACT_EVENTS,
                    Capability.RAW_PAYLOADS,
                    Capability.FINALITY,
                    Capability.DATASET_EXPORT,
                }
            ),
            metadata={
                "normalizer_version": self.normalizer_version,
                "program_logs_included": self._include_program_logs,
                "token_metadata_required": False,
                "nft_enrichment": "optional_projection",
                "read_only": True,
            },
        )

    @staticmethod
    def _extension(data: Mapping[str, Any]) -> Mapping[str, VersionedExtension]:
        return {
            "solana": VersionedExtension(
                schema_version=SOLANA_EXTENSION_VERSION,
                data=data,
            )
        }

    def _provenance(
        self, payload: object, *, context: OperationContext, scope: str
    ) -> Provenance:
        observed_at = self._clock()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise NormalizationError("normalizer clock must be timezone-aware")
        return Provenance(
            provider=self._provider,
            provider_kind="solana-json-rpc",
            request_id=context.request_id,
            scope=scope,
            observed_at=observed_at,
            raw_payload=RawPayloadRef(digest=content_digest(payload)),
        )

    def normalize(
        self, records: Sequence[object], *, context: OperationContext
    ) -> tuple[object, ...]:
        context.check_active()
        output: list[object] = []
        for value in records:
            if isinstance(value, SolanaBlockBundle):
                output.extend(self.normalize_block(value, context=context))
            elif isinstance(value, SolanaTransactionBundle):
                output.extend(self.normalize_transaction(value, context=context))
            else:
                raise NormalizationError(
                    "Solana normalizer expects SolanaBlockBundle or "
                    "SolanaTransactionBundle"
                )
            if len(output) > context.limits.max_items:
                raise ResourceLimitError("normalized Solana records exceed max_items")
        return tuple(output)

    @staticmethod
    def _block_time(value: int | None) -> datetime | None:
        return (
            None
            if value is None
            else datetime.fromtimestamp(value, tz=timezone.utc)
        )

    def normalize_block(
        self, bundle: SolanaBlockBundle, *, context: OperationContext
    ) -> tuple[object, ...]:
        finality = SolanaFinalityPolicy.state_for(bundle.commitment)
        output: list[object] = [
            BlockRecord(
                chain=self._network.to_chain_ref(),
                provenance=self._provenance(
                    {
                        "slot": bundle.slot,
                        "blockhash": bundle.blockhash,
                        "previousBlockhash": bundle.previous_blockhash,
                    },
                    context=context,
                    scope="ledger",
                ),
                ledger_position=LedgerPosition(
                    sequence=bundle.slot, hash=bundle.blockhash
                ),
                finality=finality,
                block_hash=bundle.blockhash,
                parent_hash=bundle.previous_blockhash,
                block_time=self._block_time(bundle.block_time),
                transaction_count=len(bundle.transactions),
                extensions=self._extension(
                    {
                        "parent_slot": bundle.parent_slot,
                        "commitment": bundle.commitment.value,
                    }
                ),
            )
        ]
        for transaction in bundle.transactions:
            output.extend(self.normalize_transaction(transaction, context=context))
        return tuple(output)

    def _account(
        self, address: object, *, kind: AccountKind = AccountKind.ADDRESS
    ) -> AccountRef:
        return AccountRef(
            self._network.to_chain_ref(),
            normalize_pubkey(address, field_name="account"),
            kind,
        )

    def _native_asset(self) -> AssetRef:
        return AssetRef(
            chain=self._network.to_chain_ref(),
            asset_namespace="slip44",
            asset_reference="501",
            decimals=self._network.native_decimals,
            kind=AssetKind.NATIVE,
            symbol=self._network.native_symbol,
        )

    def _token_asset(self, mint: str, decimals: int) -> AssetRef:
        mint = normalize_pubkey(mint, field_name="mint")
        metadata = self._token_metadata.get(mint)
        if metadata is not None and metadata.decimals != decimals:
            raise NormalizationError(
                f"token metadata decimals disagree with on-chain balance for {mint}"
            )
        return AssetRef(
            chain=self._network.to_chain_ref(),
            asset_namespace="spl-token",
            asset_reference=mint,
            decimals=decimals,
            kind=(
                metadata.kind if metadata is not None else AssetKind.FUNGIBLE_TOKEN
            ),
            symbol=metadata.symbol if metadata is not None else None,
        )

    @staticmethod
    def _transaction_parts(
        bundle: SolanaTransactionBundle,
    ) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
        wrapper = bundle.transaction
        transaction = wrapper.get("transaction")
        meta = wrapper.get("meta")
        if not isinstance(transaction, Mapping) or not isinstance(meta, Mapping):
            raise NormalizationError("Solana bundle requires transaction and meta mappings")
        message = transaction.get("message")
        if not isinstance(message, Mapping):
            raise NormalizationError("transaction.message must be a mapping")
        return transaction, message, meta

    @staticmethod
    def _instructions(
        message: Mapping[str, Any], meta: Mapping[str, Any]
    ) -> tuple[_Instruction, ...]:
        outer = message.get("instructions")
        if not isinstance(outer, Sequence) or isinstance(outer, (str, bytes)):
            raise NormalizationError("message.instructions must be a sequence")
        inner_groups = meta.get("innerInstructions") or ()
        if not isinstance(inner_groups, Sequence) or isinstance(
            inner_groups, (str, bytes)
        ):
            raise NormalizationError("meta.innerInstructions must be a sequence")
        inner_by_outer: dict[int, Sequence[object]] = {}
        for group in inner_groups:
            if not isinstance(group, Mapping):
                raise NormalizationError("inner instruction group must be a mapping")
            index = parse_non_negative_int(
                group.get("index"), field_name="inner instruction outer index"
            )
            values = group.get("instructions")
            if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
                raise NormalizationError("inner instructions must be a sequence")
            if index in inner_by_outer:
                raise NormalizationError("duplicate inner instruction outer index")
            inner_by_outer[index] = values
        result: list[_Instruction] = []
        event_index = 0
        for outer_index, value in enumerate(outer):
            if not isinstance(value, Mapping):
                raise NormalizationError("outer instruction must be a mapping")
            result.append(_Instruction(value, outer_index, None, event_index))
            event_index += 1
            for inner_index, inner in enumerate(inner_by_outer.get(outer_index, ())):
                if not isinstance(inner, Mapping):
                    raise NormalizationError("inner instruction must be a mapping")
                result.append(
                    _Instruction(inner, outer_index, inner_index, event_index)
                )
                event_index += 1
        unknown_groups = set(inner_by_outer) - set(range(len(outer)))
        if unknown_groups:
            raise NormalizationError("inner instructions reference a missing outer index")
        return tuple(result)

    @staticmethod
    def _program_id(
        instruction: Mapping[str, Any], account_keys: tuple[str, ...]
    ) -> str:
        if instruction.get("programId") is not None:
            return normalize_pubkey(instruction["programId"], field_name="programId")
        program_index = parse_non_negative_int(
            instruction.get("programIdIndex"), field_name="programIdIndex"
        )
        try:
            return account_keys[program_index]
        except IndexError:
            raise NormalizationError("programIdIndex is outside resolved account keys") from None

    @staticmethod
    def _instruction_accounts(
        instruction: Mapping[str, Any], account_keys: tuple[str, ...]
    ) -> tuple[str, ...]:
        values = instruction.get("accounts") or ()
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise NormalizationError("instruction accounts must be a sequence")
        result: list[str] = []
        for value in values:
            if isinstance(value, int) and not isinstance(value, bool):
                try:
                    result.append(account_keys[value])
                except IndexError:
                    raise NormalizationError(
                        "instruction account index is outside resolved account keys"
                    ) from None
            else:
                result.append(
                    normalize_pubkey(value, field_name="instruction account")
                )
        return tuple(result)

    @staticmethod
    def _parsed_instruction(
        instruction: Mapping[str, Any],
    ) -> tuple[str | None, Mapping[str, Any]]:
        parsed = instruction.get("parsed")
        if parsed is None:
            return None, {}
        if not isinstance(parsed, Mapping):
            raise NormalizationError("instruction.parsed must be a mapping")
        kind = parsed.get("type")
        info = parsed.get("info") or {}
        if kind is not None and (not isinstance(kind, str) or not kind):
            raise NormalizationError("parsed instruction type must be a string")
        if not isinstance(info, Mapping):
            raise NormalizationError("parsed instruction info must be a mapping")
        return kind, info

    @staticmethod
    def _token_balance_map(
        meta: Mapping[str, Any],
        account_keys: tuple[str, ...],
    ) -> dict[str, tuple[str, int, str | None, str]]:
        result: dict[str, tuple[str, int, str | None, str]] = {}
        for field_name in ("preTokenBalances", "postTokenBalances"):
            values = meta.get(field_name) or ()
            if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
                raise NormalizationError(f"meta.{field_name} must be a sequence")
            for value in values:
                if not isinstance(value, Mapping):
                    raise NormalizationError("token balance must be a mapping")
                account_index = parse_non_negative_int(
                    value.get("accountIndex"), field_name="token accountIndex"
                )
                try:
                    token_account = account_keys[account_index]
                except IndexError:
                    raise NormalizationError(
                        "token accountIndex is outside resolved account keys"
                    ) from None
                ui_amount = value.get("uiTokenAmount")
                if not isinstance(ui_amount, Mapping):
                    raise NormalizationError("uiTokenAmount must be a mapping")
                mint = normalize_pubkey(value.get("mint"), field_name="token mint")
                decimals = parse_non_negative_int(
                    ui_amount.get("decimals"), field_name="token decimals"
                )
                if decimals > 255:
                    raise NormalizationError("token decimals must not exceed 255")
                amount = str(
                    parse_non_negative_int(
                        ui_amount.get("amount"), field_name="token amount"
                    )
                )
                owner_raw = value.get("owner")
                owner = (
                    None
                    if owner_raw is None
                    else normalize_pubkey(owner_raw, field_name="token owner")
                )
                result[token_account] = (mint, decimals, owner, amount)
        return result

    def _logs_extension(self, meta: Mapping[str, Any]) -> dict[str, Any]:
        logs = meta.get("logMessages")
        if logs is None:
            logs = ()
        if not isinstance(logs, Sequence) or isinstance(logs, (str, bytes)):
            raise NormalizationError("meta.logMessages must be a sequence")
        if len(logs) > self._max_program_logs:
            raise ResourceLimitError("Solana program logs exceed max_program_logs")
        normalized: list[str] = []
        total_bytes = 0
        for value in logs:
            if not isinstance(value, str):
                raise NormalizationError("program log entries must be strings")
            total_bytes += len(value.encode("utf-8"))
            if total_bytes > self._max_log_bytes:
                raise ResourceLimitError("Solana program logs exceed max_log_bytes")
            normalized.append(value)
        result: dict[str, Any] = {
            "program_log_count": len(normalized),
            "program_logs_digest": content_digest(normalized),
            "program_logs_included": self._include_program_logs,
        }
        if self._include_program_logs:
            result["program_logs"] = normalized
        return result

    def normalize_transaction(
        self, bundle: SolanaTransactionBundle, *, context: OperationContext
    ) -> tuple[object, ...]:
        transaction, message, meta = self._transaction_parts(bundle)
        account_keys, lookup_tables = resolve_message_account_keys(message, meta)
        signatures = transaction.get("signatures")
        if not isinstance(signatures, Sequence) or isinstance(signatures, (str, bytes)):
            raise NormalizationError("transaction.signatures must be a sequence")
        if not signatures:
            raise NormalizationError("transaction must contain a signature")
        signature = normalize_signature(signatures[0])
        finality = SolanaFinalityPolicy.state_for(bundle.commitment)
        position = LedgerPosition(
            sequence=bundle.slot,
            hash=bundle.blockhash,
            transaction_index=bundle.transaction_index,
        )
        failed = meta.get("err") is not None
        status = TransactionStatus.FAILED if failed else TransactionStatus.SUCCEEDED
        fee = parse_non_negative_int(meta.get("fee"), field_name="transaction fee")
        participants = tuple(self._account(key) for key in dict.fromkeys(account_keys))
        version = bundle.transaction.get("version", "legacy")
        lookup_extension = [
            {
                "account_key": table.account_key,
                "writable_indexes": list(table.writable_indexes),
                "readonly_indexes": list(table.readonly_indexes),
                "writable_addresses": list(table.writable_addresses),
                "readonly_addresses": list(table.readonly_addresses),
            }
            for table in lookup_tables
        ]
        output: list[object] = [
            TransactionRecord(
                chain=self._network.to_chain_ref(),
                provenance=self._provenance(
                    bundle.transaction, context=context, scope="ledger"
                ),
                ledger_position=position,
                finality=finality,
                transaction_hash=signature,
                status=status,
                participants=participants,
                fee=ExactAmount.from_int(
                    fee, decimals=self._network.native_decimals
                ),
                block_time=self._block_time(bundle.block_time),
                extensions=self._extension(
                    {
                        "commitment": bundle.commitment.value,
                        "version": version,
                        "recent_blockhash": message.get("recentBlockhash"),
                        "failed": failed,
                        "error": meta.get("err"),
                        "compute_units_consumed": meta.get("computeUnitsConsumed"),
                        "address_lookup_tables": lookup_extension,
                        **self._logs_extension(meta),
                    }
                ),
            )
        ]

        instructions = self._instructions(message, meta)
        token_balances = self._token_balance_map(meta, account_keys)
        for native in instructions:
            program_id = self._program_id(native.value, account_keys)
            parsed_type, info = self._parsed_instruction(native.value)
            instruction_accounts = self._instruction_accounts(
                native.value, account_keys
            )
            instruction_extension = {
                "outer_index": native.outer_index,
                "inner_index": native.inner_index,
                "instruction_index": native.event_index,
                "program_id": program_id,
                "parsed_type": parsed_type,
                "stack_height": native.value.get("stackHeight"),
                "failed_transaction": failed,
                "raw_data_digest": (
                    None
                    if native.value.get("data") is None
                    else content_digest(native.value.get("data"))
                ),
            }
            output.append(
                ContractEventRecord(
                    chain=self._network.to_chain_ref(),
                    provenance=self._provenance(
                        native.value, context=context, scope="ledger"
                    ),
                    ledger_position=LedgerPosition(
                        sequence=bundle.slot,
                        hash=bundle.blockhash,
                        transaction_index=bundle.transaction_index,
                        event_index=native.event_index,
                    ),
                    finality=finality,
                    transaction_hash=signature,
                    event_index=native.event_index,
                    contract=self._account(program_id, kind=AccountKind.CONTRACT),
                    event_signature=parsed_type,
                    topics=instruction_accounts,
                    data_ref=RawPayloadRef(digest=content_digest(native.value)),
                    extensions=self._extension(instruction_extension),
                )
            )
            # Failed Solana transactions roll back all instruction effects.
            if failed or parsed_type not in {"transfer", "transferChecked"}:
                continue
            transfer = self._transfer_from_instruction(
                native,
                program_id=program_id,
                info=info,
                token_balances=token_balances,
                signature=signature,
                bundle=bundle,
                context=context,
            )
            if transfer is not None:
                output.append(transfer)

        output.extend(
            self._balance_records(
                bundle,
                account_keys=account_keys,
                token_balances=token_balances,
                context=context,
            )
        )
        return tuple(output)

    def _transfer_from_instruction(
        self,
        native: _Instruction,
        *,
        program_id: str,
        info: Mapping[str, Any],
        token_balances: Mapping[str, tuple[str, int, str | None, str]],
        signature: str,
        bundle: SolanaTransactionBundle,
        context: OperationContext,
    ) -> TransferRecord | None:
        if program_id == SYSTEM_PROGRAM_ID and "lamports" in info:
            source = self._account(info.get("source"))
            destination = self._account(info.get("destination"))
            amount = parse_non_negative_int(
                info.get("lamports"), field_name="system transfer lamports"
            )
            asset = self._native_asset()
            kind = TransferKind.NATIVE
        elif program_id in TOKEN_PROGRAM_IDS:
            source_key = normalize_pubkey(
                info.get("source"), field_name="token transfer source"
            )
            destination_key = normalize_pubkey(
                info.get("destination"), field_name="token transfer destination"
            )
            token_amount = info.get("tokenAmount")
            if token_amount is not None:
                if not isinstance(token_amount, Mapping):
                    raise NormalizationError("tokenAmount must be a mapping")
                amount = parse_non_negative_int(
                    token_amount.get("amount"), field_name="SPL token amount"
                )
                decimals = parse_non_negative_int(
                    token_amount.get("decimals"), field_name="SPL token decimals"
                )
                mint = normalize_pubkey(info.get("mint"), field_name="SPL token mint")
            else:
                source_balance = token_balances.get(source_key)
                destination_balance = token_balances.get(destination_key)
                balance = source_balance or destination_balance
                if balance is None:
                    raise NormalizationError(
                        "unchecked SPL transfer requires token-balance mint/decimals"
                    )
                mint, decimals, _owner, _balance_amount = balance
                amount = parse_non_negative_int(
                    info.get("amount"), field_name="SPL token amount"
                )
            if decimals > 255:
                raise NormalizationError("SPL token decimals must not exceed 255")
            source = self._account(source_key, kind=AccountKind.TOKEN_ACCOUNT)
            destination = self._account(
                destination_key, kind=AccountKind.TOKEN_ACCOUNT
            )
            asset = self._token_asset(mint, decimals)
            kind = TransferKind.TOKEN
        else:
            return None
        return TransferRecord(
            chain=self._network.to_chain_ref(),
            provenance=self._provenance(
                native.value, context=context, scope="ledger"
            ),
            ledger_position=LedgerPosition(
                sequence=bundle.slot,
                hash=bundle.blockhash,
                transaction_index=bundle.transaction_index,
                event_index=native.event_index,
            ),
            finality=SolanaFinalityPolicy.state_for(bundle.commitment),
            transaction_hash=signature,
            transfer_index=native.event_index,
            asset=asset,
            amount=ExactAmount.from_int(amount, decimals=asset.decimals),
            source_account=source,
            destination_account=destination,
            transfer_kind=kind,
            extensions=self._extension(
                {
                    "outer_index": native.outer_index,
                    "inner_index": native.inner_index,
                    "program_id": program_id,
                }
            ),
        )

    def _balance_records(
        self,
        bundle: SolanaTransactionBundle,
        *,
        account_keys: tuple[str, ...],
        token_balances: Mapping[str, tuple[str, int, str | None, str]],
        context: OperationContext,
    ) -> tuple[object, ...]:
        _transaction, _message, meta = self._transaction_parts(bundle)
        finality = SolanaFinalityPolicy.state_for(bundle.commitment)
        position = LedgerPosition(
            sequence=bundle.slot,
            hash=bundle.blockhash,
            transaction_index=bundle.transaction_index,
        )
        output: list[object] = []
        post_balances = meta.get("postBalances") or ()
        if not isinstance(post_balances, Sequence) or isinstance(
            post_balances, (str, bytes)
        ):
            raise NormalizationError("meta.postBalances must be a sequence")
        if len(post_balances) != len(account_keys):
            raise NormalizationError("postBalances/accountKeys length mismatch")
        for index, value in enumerate(post_balances):
            lamports = parse_non_negative_int(
                value, field_name=f"postBalances[{index}]"
            )
            output.append(
                BalanceSnapshot(
                    chain=self._network.to_chain_ref(),
                    provenance=self._provenance(
                        {"account": account_keys[index], "lamports": lamports},
                        context=context,
                        scope="ledger",
                    ),
                    ledger_position=position,
                    finality=finality,
                    account=self._account(account_keys[index]),
                    asset=self._native_asset(),
                    amount=ExactAmount.from_int(
                        lamports, decimals=self._network.native_decimals
                    ),
                    extensions=self._extension(
                        {"commitment": bundle.commitment.value}
                    ),
                )
            )

        post_values = meta.get("postTokenBalances") or ()
        seen_token_accounts: set[str] = set()
        for value in post_values:
            if not isinstance(value, Mapping):
                raise NormalizationError("post token balance must be a mapping")
            index = parse_non_negative_int(
                value.get("accountIndex"), field_name="token accountIndex"
            )
            try:
                token_account_key = account_keys[index]
            except IndexError:
                raise NormalizationError(
                    "token accountIndex is outside resolved account keys"
                ) from None
            if token_account_key in seen_token_accounts:
                raise NormalizationError("duplicate post token balance account")
            seen_token_accounts.add(token_account_key)
            mint, decimals, owner, amount = token_balances[token_account_key]
            asset = self._token_asset(mint, decimals)
            output.append(
                TokenAccountRecord(
                    chain=self._network.to_chain_ref(),
                    provenance=self._provenance(
                        value, context=context, scope="ledger"
                    ),
                    ledger_position=position,
                    finality=finality,
                    token_account=self._account(
                        token_account_key, kind=AccountKind.TOKEN_ACCOUNT
                    ),
                    owner=None if owner is None else self._account(owner),
                    asset=asset,
                    amount=ExactAmount(amount, decimals),
                    extensions=self._extension(
                        {
                            "commitment": bundle.commitment.value,
                            "nft_enrichment_applied": mint in self._token_metadata,
                        }
                    ),
                )
            )
        return tuple(output)


__all__ = [
    "SOLANA_EXTENSION_VERSION",
    "SYSTEM_PROGRAM_ID",
    "TOKEN_PROGRAM_IDS",
    "SolanaNormalizer",
    "TokenMetadata",
]
