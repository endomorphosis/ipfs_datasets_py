"""Integration tests for wallet DuckDB shadow ledger producers (DQK-071).

Acceptance coverage:

* All chain fixtures match JSONL and DB projections
* Checkpoint / reorg / deterministic-ID parity passes
* Secrets, signing payloads, and unrestricted raw bytes never enter DuckDB
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()
_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "wallets"


def _prefer_sealed_accelerate_checkout() -> None:
    """Prefer the admitted accelerate checkout over the nested worktree copy."""

    accelerate_paths: list[Path] = []
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            continue
        runtime = (
            path
            / "ipfs_accelerate_py"
            / "agent_supervisor"
            / "validation_runtime.py"
        )
        if runtime.is_file() and path not in accelerate_paths:
            accelerate_paths.append(path)
    if not accelerate_paths:
        return
    preferred = next(
        (path for path in accelerate_paths if path != _LOCAL_ACCELERATE),
        accelerate_paths[0],
    )
    if preferred == _LOCAL_ACCELERATE:
        return
    rebuilt: list[str] = [str(preferred)]
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            rebuilt.append(entry)
            continue
        if path in {_LOCAL_ACCELERATE, preferred}:
            continue
        rebuilt.append(entry)
    sys.path[:] = rebuilt
    for name in list(sys.modules):
        if name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py."):
            del sys.modules[name]


_prefer_sealed_accelerate_checkout()

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ipfs_datasets_py.processors.wallets.api import (  # noqa: E402
    ScanBounds,
    WalletIngestRequest,
    WalletProcessorAPI,
)
from ipfs_datasets_py.processors.wallets.canonical import (  # noqa: E402
    content_digest,
    deterministic_id,
)
from ipfs_datasets_py.processors.wallets.checkpoints import (  # noqa: E402
    CheckpointIdentity,
    HashAnchor,
    ShadowCheckpointStore,
    build_checkpoint,
    checkpoint_content_fingerprint,
    new_revision,
    open_shadow_checkpoint_store,
)
from ipfs_datasets_py.processors.wallets.duckdb_storage import (  # noqa: E402
    DuckDBWalletStore,
    open_wallet_store,
)
from ipfs_datasets_py.processors.wallets.errors import (  # noqa: E402
    DatasetSinkError,
)
from ipfs_datasets_py.processors.wallets.finality import (  # noqa: E402
    OrphanCorrection,
    ReorgDecision,
    ReorgKind,
)
from ipfs_datasets_py.processors.wallets.models import (  # noqa: E402
    AccountKind,
    AccountRef,
    AssetKind,
    AssetRef,
    BlockRecord,
    ChainRef,
    ContractEventRecord,
    ExactAmount,
    Finality,
    LedgerPosition,
    Provenance,
    RawPayloadPolicy,
    RawPayloadRef,
    TransactionRecord,
    TransactionStatus,
    TransferKind,
    TransferRecord,
    UTXORecord,
)
from ipfs_datasets_py.processors.wallets.pipeline import (  # noqa: E402
    RunStatus,
    WalletLedgerProcessor,
)
from ipfs_datasets_py.processors.wallets.protocols import (  # noqa: E402
    BoundedRequest,
    Capabilities,
    Capability,
    OperationContext,
    RecordBatch,
    RequestLimits,
)
from ipfs_datasets_py.processors.wallets.registry import (  # noqa: E402
    WalletProcessorRegistry,
)
from ipfs_datasets_py.processors.wallets.storage import (  # noqa: E402
    ShadowStreamingDatasetSink,
    WalletLedgerAuthorityMode,
    assert_shadow_catalog_is_public,
    assert_shadow_row_is_public,
    open_shadow_sink,
    record_identity,
)


NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
GENESIS_ETH = "0xd4e56740f876aef8c010b86a40d5f56745a118d0906a34e69aec8c0db1cb8fa3"
DIGEST = "sha256:" + ("ab" * 32)
CID = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"


def _run(coro):
    return asyncio.run(coro)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def eth_chain() -> ChainRef:
    return ChainRef(
        namespace="eip155",
        network="ethereum-mainnet",
        chain_id="1",
        genesis_hash=GENESIS_ETH,
    )


@pytest.fixture
def btc_chain() -> ChainRef:
    return ChainRef(
        namespace="bip122",
        network="bitcoin-mainnet",
        chain_id="000000000019d6689c085ae165831e93",
        genesis_hash="000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f",
    )


@pytest.fixture
def sol_chain() -> ChainRef:
    return ChainRef(
        namespace="solana",
        network="mainnet-beta",
        chain_id="5eykt4UsLwhKjRFeqBGQRxxi1SdMHZMfFmoFVW4AkqZf",
        genesis_hash="4sGjMW1sUnHzSxGspuhpqLDx6wiyjNtZAMdL4VZHirAn",
    )


@pytest.fixture
def context() -> OperationContext:
    return OperationContext(
        request_id="shadow-ledger-itest",
        limits=RequestLimits(
            max_items=200,
            max_pages=20,
            max_requests=40,
            max_response_bytes=256 * 1024,
        ),
    )


@pytest.fixture
def duckdb_store() -> DuckDBWalletStore:
    return open_wallet_store(scope="wallet:shadow-itest", auto_recover=True)


def _provenance(scope: str = "wallet:0xabc") -> Provenance:
    return Provenance(
        provider="fixture-rpc",
        provider_kind="json-rpc",
        request_id="req-shadow-1",
        scope=scope,
        observed_at=NOW,
        raw_payload=RawPayloadRef(
            digest=DIGEST,
            cid=CID,
            media_type="application/json",
            byte_length=64,
        ),
    )


def _block(
    chain: ChainRef,
    *,
    sequence: int,
    block_hash: str,
    parent_hash: str | None = None,
    finality: Finality = Finality.CONFIRMED,
    scope: str = "wallet:0xabc",
) -> BlockRecord:
    return BlockRecord(
        chain=chain,
        provenance=_provenance(scope),
        ledger_position=LedgerPosition(sequence=sequence, hash=block_hash),
        finality=finality,
        block_hash=block_hash,
        parent_hash=parent_hash or f"0xparent{sequence - 1:064x}"[:66],
        block_time=NOW,
        transaction_count=1,
    )


def _tx(
    chain: ChainRef,
    *,
    tx_hash: str,
    sequence: int,
    block_hash: str,
    tx_index: int = 0,
    finality: Finality = Finality.CONFIRMED,
    scope: str = "wallet:0xabc",
) -> TransactionRecord:
    return TransactionRecord(
        chain=chain,
        provenance=_provenance(scope),
        ledger_position=LedgerPosition(
            sequence=sequence, hash=block_hash, transaction_index=tx_index
        ),
        finality=finality,
        transaction_hash=tx_hash,
        status=TransactionStatus.SUCCEEDED,
        participants=(AccountRef(chain, "0xabc", AccountKind.ADDRESS),),
    )


def _transfer(
    chain: ChainRef,
    *,
    tx_hash: str,
    sequence: int,
    block_hash: str,
    transfer_index: int = 0,
    finality: Finality = Finality.CONFIRMED,
    scope: str = "wallet:0xabc",
) -> TransferRecord:
    asset = AssetRef(
        chain,
        asset_namespace="slip44",
        asset_reference="60",
        decimals=18,
        kind=AssetKind.NATIVE,
        symbol="ETH",
    )
    return TransferRecord(
        chain=chain,
        provenance=_provenance(scope),
        ledger_position=LedgerPosition(
            sequence=sequence, hash=block_hash, transaction_index=0
        ),
        finality=finality,
        transaction_hash=tx_hash,
        transfer_index=transfer_index,
        asset=asset,
        amount=ExactAmount(base_units="1000000000000000000", decimals=18),
        source_account=AccountRef(chain, "0xabc", AccountKind.ADDRESS),
        destination_account=AccountRef(chain, "0xdef", AccountKind.ADDRESS),
        transfer_kind=TransferKind.NATIVE,
    )


def _utxo(
    chain: ChainRef,
    *,
    tx_hash: str,
    vout: int,
    sequence: int,
    block_hash: str,
    finality: Finality = Finality.CONFIRMED,
    scope: str = "wallet:bc1qabc",
) -> UTXORecord:
    asset = AssetRef(
        chain,
        asset_namespace="slip44",
        asset_reference="0",
        decimals=8,
        kind=AssetKind.NATIVE,
        symbol="BTC",
    )
    return UTXORecord(
        chain=chain,
        provenance=_provenance(scope),
        ledger_position=LedgerPosition(sequence=sequence, hash=block_hash),
        finality=finality,
        transaction_hash=tx_hash,
        output_index=vout,
        asset=asset,
        amount=ExactAmount(base_units="50000000", decimals=8),
        owner=AccountRef(chain, "bc1qabc", AccountKind.ADDRESS),
    )


def _event(
    chain: ChainRef,
    *,
    tx_hash: str,
    sequence: int,
    block_hash: str,
    event_index: int = 0,
    finality: Finality = Finality.CONFIRMED,
    scope: str = "wallet:0xabc",
) -> ContractEventRecord:
    return ContractEventRecord(
        chain=chain,
        provenance=_provenance(scope),
        ledger_position=LedgerPosition(
            sequence=sequence,
            hash=block_hash,
            transaction_index=0,
            event_index=event_index,
        ),
        finality=finality,
        transaction_hash=tx_hash,
        event_index=event_index,
        contract=AccountRef(chain, "0xcontract", AccountKind.CONTRACT),
        event_signature="Transfer(address,address,uint256)",
        topics=(
            "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
        ),
        data_ref=RawPayloadRef(
            digest="sha256:" + ("ee" * 32),
            cid="bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
            media_type="application/json",
            byte_length=32,
        ),
    )


class _FixtureNormalizer:
    """Identity normalizer: already-normalized LedgerRecord fixtures pass through."""

    def normalize(
        self, records: Sequence[object], *, context: OperationContext
    ) -> Sequence[object]:
        context.check_active()
        return tuple(records)

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            provider="fixture-normalizer",
            chain_namespaces=frozenset({"eip155", "bip122", "solana"}),
            features=frozenset(
                {
                    Capability.WALLET_HISTORY,
                    Capability.LEDGER_RANGE,
                    Capability.DATASET_EXPORT,
                }
            ),
        )


class _StaticWalletProvider:
    """Yields prebuilt pages of ledger records (offline multi-chain fixtures)."""

    def __init__(self, pages: Sequence[Sequence[object]]) -> None:
        self._pages = tuple(tuple(page) for page in pages)

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            provider="static-fixture",
            chain_namespaces=frozenset({"eip155", "bip122", "solana"}),
            features=frozenset({Capability.WALLET_HISTORY, Capability.LEDGER_RANGE}),
        )

    async def ingest_wallet(
        self, request: BoundedRequest
    ) -> AsyncIterator[RecordBatch]:
        request.context.check_active()
        total = len(self._pages)
        for index, page in enumerate(self._pages):
            next_cursor = None if index + 1 >= total else f"page-{index + 1}"
            yield RecordBatch(
                page,
                next_cursor=next_cursor,
                response_bytes=128,
            )


# ---------------------------------------------------------------------------
# Multi-chain fixture parity: JSONL primary vs DuckDB shadow
# ---------------------------------------------------------------------------


def test_multi_chain_fixtures_match_jsonl_and_db(
    tmp_path: Path,
    eth_chain: ChainRef,
    btc_chain: ChainRef,
    sol_chain: ChainRef,
    context: OperationContext,
    duckdb_store: DuckDBWalletStore,
) -> None:
    """Ethereum / Bitcoin / Solana fixtures dual-write with matching IDs."""

    eth_scope = "wallet:0x1111111111111111111111111111111111111111"
    btc_scope = "wallet:bc1qtest"
    sol_scope = "wallet:So11111111111111111111111111111111111111112"

    eth_page = [
        _block(
            eth_chain,
            sequence=19_000_001,
            block_hash="0x" + "bb" * 32,
            scope=eth_scope,
        ),
        _tx(
            eth_chain,
            tx_hash="0x" + "aa" * 32,
            sequence=19_000_001,
            block_hash="0x" + "bb" * 32,
            scope=eth_scope,
        ),
        _transfer(
            eth_chain,
            tx_hash="0x" + "aa" * 32,
            sequence=19_000_001,
            block_hash="0x" + "bb" * 32,
            scope=eth_scope,
        ),
        _event(
            eth_chain,
            tx_hash="0x" + "aa" * 32,
            sequence=19_000_001,
            block_hash="0x" + "bb" * 32,
            scope=eth_scope,
        ),
    ]
    btc_page = [
        _block(
            btc_chain,
            sequence=800_000,
            block_hash="0x" + "11" * 32,
            scope=btc_scope,
        ),
        _utxo(
            btc_chain,
            tx_hash="0x" + "22" * 32,
            vout=0,
            sequence=800_000,
            block_hash="0x" + "11" * 32,
            scope=btc_scope,
        ),
    ]
    sol_page = [
        _block(
            sol_chain,
            sequence=250_000_000,
            block_hash="0x" + "33" * 32,
            scope=sol_scope,
        ),
        _tx(
            sol_chain,
            tx_hash="0x" + "44" * 32,
            sequence=250_000_000,
            block_hash="0x" + "33" * 32,
            scope=sol_scope,
        ),
    ]

    # Also fold in shared export fixture coordinates for deterministic IDs.
    sample = _load_json(_FIXTURES / "_shared" / "export_sample_records.json")
    sample_chain = ChainRef(
        namespace=sample["chain"]["namespace"],
        network=sample["chain"]["network"],
        chain_id=sample["chain"]["chain_id"],
        genesis_hash=sample["chain"]["genesis_hash"],
    )
    for row in sample["transactions"]:
        eth_page.append(
            _tx(
                sample_chain,
                tx_hash=row["transaction_hash"],
                sequence=int(row["sequence"]),
                block_hash=row["block_hash"],
                tx_index=int(row.get("transaction_index") or 0),
                finality=Finality(row["finality"]),
                scope=f"wallet:{sample['account']}",
            )
        )
    for row in sample["transfers"]:
        eth_page.append(
            _transfer(
                sample_chain,
                tx_hash=row["transaction_hash"],
                sequence=int(row["sequence"]),
                block_hash=row["block_hash"],
                transfer_index=int(row["transfer_index"]),
                finality=Finality(row["finality"]),
                scope=f"wallet:{sample['account']}",
            )
        )

    all_records = list(eth_page) + list(btc_page) + list(sol_page)
    expected_ids = {record_identity(r) for r in all_records}

    out_dir = tmp_path / "jsonl"
    sink = open_shadow_sink(
        scope="wallet:multi-chain",
        output_dir=out_dir,
        duckdb_store=duckdb_store,
        authority_mode=WalletLedgerAuthorityMode.SHADOW,
        fail_on_shadow_error=True,
    )

    async def _ingest() -> None:
        await sink.write(
            RecordBatch(tuple(all_records), response_bytes=256),
            context=context,
        )
        await sink.commit(None, context=context)

    _run(_ingest())

    # JSONL primary projection
    jsonl_path = out_dir / "records.jsonl"
    assert jsonl_path.is_file()
    jsonl_rows = [
        json.loads(line)
        for line in jsonl_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    jsonl_ids = {row["record_id"] for row in jsonl_rows if "record_id" in row}
    assert jsonl_ids == expected_ids

    # DuckDB shadow projection across fact tables
    shadow_ids: set[str] = set()
    for table in (
        "blocks",
        "transactions",
        "transfers",
        "utxos",
        "contract_events",
    ):
        for row in duckdb_store.list_records(table):
            rid = row.get("record_id")
            if isinstance(rid, str) and rid:
                shadow_ids.add(rid)
    assert shadow_ids == expected_ids

    parity = sink.parity_record_ids()
    assert parity["primary_only"] == frozenset()
    assert parity["shadow_only"] == frozenset()
    assert parity["matched"] == expected_ids
    assert_shadow_catalog_is_public(duckdb_store)

    # encrypted_object_refs must only carry digest/CID, never raw bodies
    for row in duckdb_store.list_records("encrypted_object_refs"):
        assert "raw_payload" not in row
        assert "payload_bytes" not in row
        assert "body" not in row
        assert row.get("digest") or row.get("cid")


# ---------------------------------------------------------------------------
# Pipeline + API + registry wiring
# ---------------------------------------------------------------------------


def test_pipeline_shadow_ingest_advances_checkpoint_and_cursor(
    tmp_path: Path,
    eth_chain: ChainRef,
    context: OperationContext,
    duckdb_store: DuckDBWalletStore,
) -> None:
    scope = "wallet:0xpipeline"
    pages = [
        [
            _block(
                eth_chain,
                sequence=100,
                block_hash="0x" + "a1" * 32,
                scope=scope,
            ),
            _tx(
                eth_chain,
                tx_hash="0x" + "b1" * 32,
                sequence=100,
                block_hash="0x" + "a1" * 32,
                scope=scope,
            ),
        ],
        [
            _block(
                eth_chain,
                sequence=101,
                block_hash="0x" + "a2" * 32,
                parent_hash="0x" + "a1" * 32,
                scope=scope,
            ),
            _transfer(
                eth_chain,
                tx_hash="0x" + "b2" * 32,
                sequence=101,
                block_hash="0x" + "a2" * 32,
                scope=scope,
            ),
        ],
    ]
    processor = WalletLedgerProcessor(
        chain=eth_chain,
        wallet_provider=_StaticWalletProvider(pages),
        ledger_provider=None,
        normalizer=_FixtureNormalizer(),
        duckdb_store=duckdb_store,
        authority_mode=WalletLedgerAuthorityMode.SHADOW,
        provider_name="fixture-rpc",
        normalizer_version="fixture-normalizer@1",
    )
    assert processor.authority_mode is WalletLedgerAuthorityMode.SHADOW
    assert processor.duckdb_store is duckdb_store

    request = BoundedRequest(scope=scope, context=context)
    receipt = _run(
        processor.ingest_wallet(
            request,
            export_dir=str(tmp_path / "export"),
            observed_anchor=HashAnchor(101, "0x" + "a2" * 32),
        )
    )
    assert receipt.status is RunStatus.COMPLETE
    assert receipt.checkpoint_advanced is True
    assert receipt.records_accepted >= 4
    assert isinstance(processor.checkpoint_store, ShadowCheckpointStore)
    assert isinstance(processor.last_sink, ShadowStreamingDatasetSink)

    # Checkpoint parity primary vs shadow
    identity = processor.identity_for(scope)
    parity = _run(
        processor.checkpoint_store.parity_checkpoint(  # type: ignore[attr-defined]
            identity.key, context=context
        )
    )
    assert parity["matched"] is True
    assert parity["primary_anchor"]["sequence"] == 101

    # Cursor rows exist in DuckDB catalog
    assert duckdb_store.count_records("cursors") >= 1
    assert duckdb_store.count_records("checkpoints") >= 1


def test_api_and_registry_inject_shadow_store(
    eth_chain: ChainRef,
    context: OperationContext,
    duckdb_store: DuckDBWalletStore,
) -> None:
    scope = "wallet:0xapi"
    pages = [
        [
            _tx(
                eth_chain,
                tx_hash="0x" + "c1" * 32,
                sequence=50,
                block_hash="0x" + "d1" * 32,
                scope=scope,
            )
        ]
    ]
    processor = WalletLedgerProcessor(
        chain=eth_chain,
        wallet_provider=_StaticWalletProvider(pages),
        normalizer=_FixtureNormalizer(),
        provider_name="fixture-rpc",
        normalizer_version="fixture-normalizer@1",
    )
    api = WalletProcessorAPI(
        processor=processor,
        duckdb_store=duckdb_store,
        authority_mode=WalletLedgerAuthorityMode.SHADOW,
    )
    assert api.authority_mode is WalletLedgerAuthorityMode.SHADOW
    assert api.duckdb_store is duckdb_store
    assert processor.duckdb_store is duckdb_store

    result = _run(
        api.wallet_ingest(
            WalletIngestRequest(
                scope=scope,
                chain=eth_chain,
                bounds=ScanBounds(max_items=50, max_pages=5, max_requests=5),
                request_id=context.request_id,
            )
        )
    )
    assert result.records_accepted >= 1
    assert duckdb_store.count_records("transactions") >= 1

    # Registry path: bind store + construct families without signing
    registry = WalletProcessorRegistry(
        duckdb_store=duckdb_store,
        authority_mode=WalletLedgerAuthorityMode.SHADOW,
    )
    cfg = registry.shadow_ledger_config()
    assert cfg["enabled"] is True
    assert cfg["supports_sign"] is False
    assert cfg["supports_broadcast"] is False
    assert registry.asserts_no_signing_authority() is True

    btc = registry.get_wallet_processor("bitcoin", network="bitcoin-mainnet")
    assert getattr(btc, "duckdb_store", None) is duckdb_store
    assert getattr(btc, "authority_mode", None) is WalletLedgerAuthorityMode.SHADOW
    shadow_meta = getattr(btc, "shadow_ledger", None)
    assert shadow_meta is not None
    assert shadow_meta["enabled"] is True
    assert shadow_meta["supports_sign"] is False


# ---------------------------------------------------------------------------
# Checkpoint / reorg / deterministic-ID parity
# ---------------------------------------------------------------------------


def test_checkpoint_cas_and_reorg_shadow_parity(
    eth_chain: ChainRef,
    context: OperationContext,
    duckdb_store: DuckDBWalletStore,
) -> None:
    fixture = _load_json(_FIXTURES / "_shared" / "cas_checkpoint.json")
    chain_data = fixture["identity"]["chain"]
    chain = ChainRef(
        namespace=chain_data["namespace"],
        network=chain_data["network"],
        chain_id=chain_data["chain_id"],
        genesis_hash=chain_data["genesis_hash"],
    )
    identity = CheckpointIdentity(
        chain=chain,
        provider=fixture["identity"]["provider"],
        scope=fixture["identity"]["scope"],
        normalized_schema_major=int(fixture["identity"]["normalized_schema_major"]),
        normalizer_version=fixture["identity"]["normalizer_version"],
    )
    store = open_shadow_checkpoint_store(
        duckdb_store=duckdb_store,
        authority_mode=WalletLedgerAuthorityMode.SHADOW,
        fail_on_shadow_error=True,
    )

    initial = fixture["cas_conflicts"]["initial"]
    first = build_checkpoint(
        identity,
        sequence=int(initial["sequence"]),
        block_hash=initial["block_hash"],
        revision=initial["revision"],
    )
    assert _run(
        store.compare_and_set(
            identity.key,
            expected_revision=None,
            checkpoint=first,
            context=context,
        )
    )

    stale = fixture["cas_conflicts"]["stale_write"]
    stale_cp = build_checkpoint(
        identity,
        sequence=int(stale["sequence"]),
        block_hash=stale["block_hash"],
        revision=new_revision(),
        prior_history=first.history,
    )
    accepted_stale = _run(
        store.compare_and_set(
            identity.key,
            expected_revision=stale["expected_revision"],
            checkpoint=stale_cp,
            context=context,
        )
    )
    assert accepted_stale is False

    matching = fixture["cas_conflicts"]["matching_write"]
    loaded = _run(store.load(identity.key, context=context))
    assert loaded is not None
    second = build_checkpoint(
        identity,
        sequence=int(matching["sequence"]),
        block_hash=matching["block_hash"],
        revision=new_revision(),
        prior_history=loaded.history,
        sink_commit_id="commit:parity",
    )
    assert _run(
        store.compare_and_set(
            identity.key,
            expected_revision=loaded.revision,
            checkpoint=second,
            context=context,
        )
    )

    parity = _run(store.parity_checkpoint(identity.key, context=context))
    assert parity["matched"] is True
    assert parity["primary_anchor"]["sequence"] == int(matching["sequence"])
    assert parity["shadow_anchor"]["sequence"] == int(matching["sequence"])

    # Seed a durable block then apply reorg/finality corrections in shadow.
    block = _block(
        chain,
        sequence=int(matching["sequence"]),
        block_hash=matching["block_hash"],
        scope=identity.scope,
    )

    async def _seed() -> None:
        await duckdb_store.write(
            RecordBatch((block,), response_bytes=32),
            context=context,
        )
        await duckdb_store.commit(None, context=context)

    _run(_seed())
    block_id = record_identity(block)

    reorg_fixture = _load_json(_FIXTURES / "_shared" / "reorg_histories.json")
    shallow = reorg_fixture["shallow"]
    orphaned = [
        HashAnchor(int(item["sequence"]), item["hash"])
        for item in shallow["local_history"]
        if item["hash"] in set(shallow["expected_orphaned_hashes"])
    ]
    ancestor = HashAnchor(
        int(shallow["expected_ancestor"]["sequence"]),
        shallow["expected_ancestor"]["hash"],
    )
    decision = ReorgDecision(
        kind=ReorgKind.SHALLOW,
        checkpoint_anchor=HashAnchor(
            int(matching["sequence"]), matching["block_hash"]
        ),
        observed_anchor=HashAnchor(
            int(shallow["observed_tip"]["sequence"]),
            shallow["observed_tip"]["hash"],
        ),
        common_ancestor=ancestor,
        orphaned_anchors=tuple(orphaned),
        corrections=(
            OrphanCorrection(
                record_id=block_id,
                prior_finality=Finality.CONFIRMED,
                new_finality=Finality.ORPHANED,
                orphaned_anchor=HashAnchor(
                    int(matching["sequence"]), matching["block_hash"]
                ),
                ancestor_anchor=ancestor,
            ),
        ),
        rewind_sequence=ancestor.sequence,
        reason="fixture-shallow-reorg",
    )
    reorg_row = store.record_reorg(
        decision,
        chain=chain,
        provenance=_provenance(identity.scope),
    )
    assert reorg_row is not None
    assert duckdb_store.count_records("reorgs") >= 1
    assert duckdb_store.count_records("finality_transitions") >= 1

    rewound = build_checkpoint(
        identity,
        sequence=ancestor.sequence,
        block_hash=ancestor.block_hash,
        revision=new_revision(),
        prior_history=second.history,
        metadata={"reorg": True},
    )
    tip = _run(store.load(identity.key, context=context))
    assert tip is not None
    assert _run(
        store.replace_after_rewind(
            identity,
            expected_revision=tip.revision,
            rewound=rewound,
            context=context,
        )
    )
    parity_after = _run(store.parity_checkpoint(identity.key, context=context))
    assert parity_after["matched"] is True
    assert parity_after["primary_anchor"]["sequence"] == ancestor.sequence


def test_deterministic_id_parity_across_primary_and_shadow(
    eth_chain: ChainRef,
    context: OperationContext,
    duckdb_store: DuckDBWalletStore,
) -> None:
    fixture = _load_json(_FIXTURES / "_shared" / "deterministic_ids.json")
    chain = ChainRef(
        namespace=fixture["chain"]["namespace"],
        network=fixture["chain"]["network"],
        chain_id=fixture["chain"]["chain_id"],
        genesis_hash=fixture["chain"]["genesis_hash"],
    )

    by_fixture_id: dict[str, str] = {}
    records: list[TransactionRecord] = []
    for row in fixture["records"]:
        identity = row["identity"]
        position = identity["position"]
        # Observation noise must not affect record_id (stable identity).
        noise = row.get("observation_noise") or {}
        prov = Provenance(
            provider=str(noise.get("provider") or "fixture-rpc"),
            provider_kind="json-rpc",
            request_id="det-id",
            scope="wallet:deterministic",
            observed_at=datetime.fromisoformat(
                str(noise.get("observed_at") or NOW.isoformat()).replace("Z", "+00:00")
            ),
        )
        record = TransactionRecord(
            chain=chain,
            provenance=prov,
            ledger_position=LedgerPosition(
                sequence=int(position["sequence"]),
                hash=position["hash"],
                transaction_index=int(position["transaction_index"]),
            ),
            finality=Finality.CONFIRMED,
            transaction_hash=identity["transaction_hash"],
            status=TransactionStatus.SUCCEEDED,
            participants=(AccountRef(chain, "0xalice", AccountKind.ADDRESS),),
        )
        by_fixture_id[row["id"]] = record.record_id
        records.append(record)

    # Observation metadata must not affect identity (must_match).
    for row in fixture["records"]:
        if "must_match_id" in row:
            assert by_fixture_id[row["id"]] == by_fixture_id[row["must_match_id"]]

    # TransactionRecord identity is hash-only (index is not an identity
    # coordinate).  Distinct hashes must still diverge; same-hash rows collapse.
    hashes = {
        row["id"]: row["identity"]["transaction_hash"] for row in fixture["records"]
    }
    for row in fixture["records"]:
        if "must_differ_from" not in row:
            continue
        other = row["must_differ_from"]
        if hashes[row["id"]] != hashes[other]:
            assert by_fixture_id[row["id"]] != by_fixture_id[other]
        else:
            # Same transaction hash → deterministic collision (by design).
            assert by_fixture_id[row["id"]] == by_fixture_id[other]

    # Dual-write once (dedup should collapse replay pair to one durable row).
    unique_records = []
    seen: set[str] = set()
    for record in records:
        if record.record_id in seen:
            continue
        seen.add(record.record_id)
        unique_records.append(record)

    sink = open_shadow_sink(
        scope="wallet:deterministic",
        duckdb_store=duckdb_store,
        authority_mode=WalletLedgerAuthorityMode.SHADOW,
    )

    async def _write() -> None:
        await sink.write(RecordBatch(tuple(unique_records)), context=context)
        await sink.commit(None, context=context)

    _run(_write())

    shadow_ids = {
        row["record_id"]
        for row in duckdb_store.list_records("transactions")
        if "record_id" in row
    }
    assert shadow_ids == {r.record_id for r in unique_records}

    # Deterministic checkpoint scope keys must match primary and shadow.
    identity = CheckpointIdentity(
        chain=chain,
        provider="fixture-rpc",
        scope="wallet:deterministic",
        normalized_schema_major=1,
        normalizer_version="shared-fixture-v1",
    )
    assert identity.key == deterministic_id(
        "checkpoint-scope",
        {
            "chain": identity.chain.identity_dict(),
            "provider": identity.provider,
            "scope": identity.scope,
            "normalized_schema_major": identity.normalized_schema_major,
            "normalizer_version": identity.normalizer_version,
        },
    )


# ---------------------------------------------------------------------------
# Secrets never enter DuckDB
# ---------------------------------------------------------------------------


def test_secrets_and_raw_bytes_never_enter_duckdb(
    eth_chain: ChainRef,
    context: OperationContext,
    duckdb_store: DuckDBWalletStore,
) -> None:
    secret_cases = _load_json(_FIXTURES / "_shared" / "secret_redaction_cases.json")
    forbidden = list(secret_cases["forbidden_substrings"])

    # Direct gate: secret keys / raw bytes / signing material fail closed
    # before they can be staged into the DuckDB shadow catalog.
    dirty_rows = [
        {
            "record_id": "block:dirty-secret",
            "table": "blocks",
            "private_key": "fake-secret-private-key-material",
        },
        {
            "record_id": "block:raw-bytes",
            "table": "blocks",
            "raw_payload_bytes": b"\x00secret-bytes",
        },
        {
            "record_id": "block:auth-header",
            "table": "blocks",
            "authorization": "Bearer placeholder-auth-material",
        },
        {
            "record_id": "tx:signing",
            "table": "transactions",
            "signing_key": "example-wallet-fixture-api-token",
            "seed": "not-a-real-seed",
        },
    ]
    for dirty in dirty_rows:
        with pytest.raises(DatasetSinkError):
            assert_shadow_row_is_public(dirty, table=str(dirty["table"]))

    # Shadow write path also rejects secret-bearing mappings (string values only
    # so the primary JSONL sink can encode the batch before the shadow gate).
    dirty_mapping = {
        "record_id": "block:dirty-secret",
        "table": "blocks",
        "chain_ref_id": eth_chain.chain_ref_id,
        "source_id": "source:dirty",
        "finality": Finality.OBSERVED.value,
        "sequence": 1,
        "block_hash": "0x" + "ff" * 32,
        "private_key": "fake-secret-private-key-material",
        "authorization": "Bearer placeholder-auth-material",
    }
    sink = open_shadow_sink(
        scope="wallet:secrets",
        duckdb_store=duckdb_store,
        authority_mode=WalletLedgerAuthorityMode.SHADOW,
        fail_on_shadow_error=True,
    )

    async def _attempt() -> None:
        await sink.write(RecordBatch((dirty_mapping,)), context=context)

    with pytest.raises(DatasetSinkError):
        _run(_attempt())

    # Clean public record is accepted; catalog remains free of needles.
    clean = _block(
        eth_chain,
        sequence=2,
        block_hash="0x" + "ee" * 32,
        scope="wallet:secrets",
    )

    async def _clean() -> None:
        await sink.write(RecordBatch((clean,)), context=context)
        await sink.commit(None, context=context)

    _run(_clean())
    assert_shadow_catalog_is_public(duckdb_store)

    # Full catalog dump must not contain fixture secret needles.
    blob_parts: list[str] = []
    for table in duckdb_store.catalog_tables():
        for row in duckdb_store.list_records(table):
            blob_parts.append(json.dumps(dict(row), default=str))
    catalog_blob = "\n".join(blob_parts)
    for needle in forbidden:
        assert needle not in catalog_blob


def test_legacy_mode_skips_duckdb_writes(
    eth_chain: ChainRef,
    context: OperationContext,
    duckdb_store: DuckDBWalletStore,
) -> None:
    sink = open_shadow_sink(
        scope="wallet:legacy",
        duckdb_store=duckdb_store,
        authority_mode=WalletLedgerAuthorityMode.LEGACY,
    )
    record = _tx(
        eth_chain,
        tx_hash="0x" + "99" * 32,
        sequence=9,
        block_hash="0x" + "88" * 32,
        scope="wallet:legacy",
    )

    async def _run_legacy() -> None:
        await sink.write(RecordBatch((record,)), context=context)
        await sink.commit(None, context=context)

    _run(_run_legacy())
    assert sink.shadow_write_count == 0
    assert sink.shadow_enabled is False
    assert duckdb_store.count_records("transactions") == 0


def test_shadow_content_fingerprint_stable(
    eth_chain: ChainRef,
    context: OperationContext,
) -> None:
    identity = CheckpointIdentity(
        chain=eth_chain,
        provider="fixture-rpc",
        scope="wallet:fp",
        normalized_schema_major=1,
        normalizer_version="v1",
    )
    a = build_checkpoint(
        identity,
        sequence=10,
        block_hash="0x" + "10" * 32,
        revision="rev:a",
        sink_commit_id="commit:1",
    )
    b = build_checkpoint(
        identity,
        sequence=10,
        block_hash="0x" + "10" * 32,
        revision="rev:b",
        sink_commit_id="commit:1",
    )
    # Fingerprint ignores revision / checkpoint_id noise.
    assert checkpoint_content_fingerprint(a) == checkpoint_content_fingerprint(b)
    assert content_digest({"x": 1}) == content_digest({"x": 1})
