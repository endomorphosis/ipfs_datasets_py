"""Ethereum/EVM chain contract over the shared wallet conformance harness."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from conformance import (  # noqa: E402
    FixtureTransport,
    ProviderContract,
    WalletProcessorConformanceMixin,
)
from ipfs_datasets_py.processors.wallets.ethereum import (  # noqa: E402
    ETHEREUM_MAINNET,
    ETHEREUM_MAINNET_GENESIS_HASH,
    EthereumLedgerProvider,
    EthereumNormalizer,
    EvmBlockBundle,
)
from ipfs_datasets_py.processors.wallets.errors import ProviderError  # noqa: E402
from ipfs_datasets_py.processors.wallets.models import (  # noqa: E402
    ContractEventRecord,
    Finality,
    TransactionRecord,
    TransferRecord,
)
from ipfs_datasets_py.processors.wallets.protocols import (  # noqa: E402
    BoundedRequest,
    OperationContext,
    RequestLimits,
)


FIXTURE_DIR = (
    Path(__file__).resolve().parents[3] / "fixtures" / "wallets" / "ethereum"
)
SESSION = json.loads((FIXTURE_DIR / "rpc_session.json").read_text(encoding="utf-8"))


class _FixtureRpc:
    def __init__(self, session: Mapping[str, Any]) -> None:
        self.session = session

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
        del url, request_id, headers
        context.check_active()
        arguments = tuple(params)
        if method == "eth_chainId":
            return self.session["chain_id_result"]
        if method == "eth_getBlockByNumber":
            tag = str(arguments[0])
            return {
                "0x0": self.session["genesis"],
                "0x10": self.session["block"],
                "latest": self.session["latest"],
                "safe": self.session["safe"],
                "finalized": self.session["finalized"],
            }[tag]
        if method == "eth_getTransactionReceipt":
            return self.session["receipts"][str(arguments[0])]
        if method == "trace_transaction":
            return self.session["traces"].get(str(arguments[0]), [])
        if method == "eth_getBalance":
            return self.session["balance_result"]
        raise ProviderError(f"missing fixture response for {method}")


def ethereum_contract() -> ProviderContract:
    return ProviderContract(
        name="ethereum-mainnet",
        chain_namespace="eip155",
        network="ethereum-mainnet",
        chain_id="1",
        genesis_hash=ETHEREUM_MAINNET_GENESIS_HASH,
        fixture_subdir="ethereum",
        provider_name="fixture-ethereum-rpc",
        import_modules=(
            "ipfs_datasets_py.processors.wallets.ethereum",
            "ipfs_datasets_py.processors.wallets.ethereum.rpc",
            "ipfs_datasets_py.processors.wallets.ethereum.normalizer",
            "ipfs_datasets_py.processors.wallets.ethereum.finality",
        ),
        metadata={
            "read_only": True,
            "token_metadata_required": False,
            "trace_capability": "optional",
        },
    )


class TestEthereumSharedConformance(WalletProcessorConformanceMixin):
    """Run every mandatory shared check without Ethereum-specific skips."""

    def provider_contract(self) -> ProviderContract:
        return ethereum_contract()

    def fixture_transport(self) -> FixtureTransport:
        return FixtureTransport()


def test_fixture_manifest_is_active_and_maps_every_ethereum_obligation() -> None:
    manifest = json.loads(
        (FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["goal_id"] == "WALPROC-G300"
    assert manifest["task_id"] == "WALPROC-018"
    assert manifest["classification"]["status"] == "active"
    assert set(manifest["coverage"]) == {
        "chain_and_genesis_identity",
        "account_balance_history",
        "legacy_and_eip1559",
        "receipts_and_reverts",
        "native_and_contract_creation",
        "erc20_erc721_erc1155",
        "removed_logs",
        "optional_traces",
        "safe_finalized_and_confirmation_fallback",
        "reorg_corrections",
        "read_only_surface",
    }
    for filename in manifest["files"]:
        assert (FIXTURE_DIR / filename).is_file()


def test_fixture_driven_provider_normalizer_and_export_records_compose() -> None:
    transport = _FixtureRpc(SESSION)
    provider = EthereumLedgerProvider(
        transport,
        endpoint="https://fixture.invalid",
        network=ETHEREUM_MAINNET,
        include_traces=True,
    )
    context = OperationContext(
        "ethereum-contract",
        limits=RequestLimits(
            max_items=100,
            max_pages=2,
            max_requests=20,
            max_response_bytes=2_000_000,
        ),
    )

    async def ingest() -> tuple[object, ...]:
        await provider.validate_identity(context=context)
        request = BoundedRequest(
            scope="ledger",
            context=context,
            start_position=16,
            end_position=16,
        )
        batches = [batch async for batch in provider.ingest_ledger(request)]
        normalizer = EthereumNormalizer(
            ETHEREUM_MAINNET,
            provider="fixture-ethereum-rpc",
            clock=lambda: datetime(2026, 7, 29, tzinfo=timezone.utc),
        )
        return normalizer.normalize(batches[0].records, context=context)

    records = asyncio.run(ingest())
    assert any(isinstance(record, TransactionRecord) for record in records)
    assert any(isinstance(record, ContractEventRecord) for record in records)
    assert any(
        isinstance(record, TransferRecord)
        and record.asset.asset_namespace == "erc20"
        and record.extensions["ethereum"].data["token_metadata_complete"] is False
        for record in records
    )
    assert any(
        isinstance(record, TransferRecord)
        and record.extensions["ethereum"].data.get("internal") is True
        for record in records
    )
    assert any(record.finality is Finality.REVERTED for record in records)
    assert any(record.finality is Finality.ORPHANED for record in records)
    # All records are directly consumable by the shared deterministic exporter.
    assert all(callable(getattr(record, "to_dict", None)) for record in records)
    assert all(record.to_dict()["record_id"] == record.record_id for record in records)


def test_read_only_contract_has_no_signing_or_broadcast_authority() -> None:
    provider = EthereumLedgerProvider(
        _FixtureRpc(SESSION),
        endpoint="https://fixture.invalid",
        network=ETHEREUM_MAINNET,
    )
    forbidden = (
        "sign",
        "send_transaction",
        "send_raw_transaction",
        "broadcast",
        "submit",
        "private_key",
        "account_unlock",
    )
    assert all(not hasattr(provider, name) for name in forbidden)
    assert provider.capabilities.metadata["read_only"] is True
    assert ethereum_contract().metadata["token_metadata_required"] is False


def test_bundle_type_is_the_only_native_normalizer_input() -> None:
    receipts = tuple(SESSION["receipts"].values())
    bundle = EvmBlockBundle(
        block=SESSION["block"],
        receipts=receipts,
        traces={transaction_hash: None for transaction_hash in SESSION["receipts"]},
        trace_capability=False,
    )
    normalizer = EthereumNormalizer(
        ETHEREUM_MAINNET,
        clock=lambda: datetime(2026, 7, 29, tzinfo=timezone.utc),
    )
    records = normalizer.normalize(
        (bundle,),
        context=OperationContext(
            "bundle-contract",
            limits=RequestLimits(max_items=100),
        ),
    )
    assert records
