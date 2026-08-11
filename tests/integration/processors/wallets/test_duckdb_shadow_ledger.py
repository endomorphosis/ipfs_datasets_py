"""Integration tests for processor wallet DuckDB shadow ledger (DQK-071).

Acceptance:

* All chain fixtures match JSONL and DB projections
* Checkpoint / reorg / deterministic-ID parity passes
* Secrets, signing payloads and unrestricted raw bytes never enter DuckDB
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")

_REPO_ROOT = Path(__file__).resolve().parents[4]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()


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

import pytest

from ipfs_datasets_py.processors.wallets.api import (
    WalletProcessorAPI,
    reset_api_shadow_store,
    set_api_shadow_enabled,
)
from ipfs_datasets_py.processors.wallets.checkpoints import (
    CheckpointIdentity,
    HashAnchor,
    InMemoryCheckpointStore,
    build_checkpoint,
    checkpoint_content_fingerprint,
    new_revision,
)
from ipfs_datasets_py.processors.wallets.duckdb_schema import (
    project_ledger_record_rows,
)
from ipfs_datasets_py.processors.wallets.duckdb_storage import (
    DuckDBWalletStore,
    open_wallet_store,
)
from ipfs_datasets_py.processors.wallets.errors import (
    DatasetSinkError,
    InvalidRequestError,
)
from ipfs_datasets_py.processors.wallets.finality import (
    OrphanCorrection,
    ReorgDecision,
    ReorgKind,
)
from ipfs_datasets_py.processors.wallets.models import (
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
    TransferKind,
    TransferRecord,
    TransactionRecord,
    TransactionStatus,
    UTXORecord,
)
from ipfs_datasets_py.processors.wallets.pipeline import (
    RunStatus,
    WalletLedgerProcessor,
)
from ipfs_datasets_py.processors.wallets.protocols import (
    BoundedRequest,
    Capabilities,
    Capability,
    OperationContext,
    RecordBatch,
    RequestLimits,
)
from ipfs_datasets_py.processors.wallets.registry import (
    WalletProcessorRegistry,
    attach_shadow_ledger,
    build_wallet_ledger_processor_from_options,
    reset_registry_shadow_store,
    resolve_shadow_store_from_options,
)
from ipfs_datasets_py.processors.wallets.storage import (
    StreamingDatasetSink,
    assert_shadow_catalog_excludes_secrets,
    compare_jsonl_db_projections,
    record_identity,
)


NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
ETH_GENESIS = "0xd4e56740f876aef8c010b86a40d5f56745a118d0906a34e69aec8c0db1cb8fa3"
BTC_GENESIS = "0x000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f"
SOL_GENESIS = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"
DIGEST = "sha256:" + ("ab" * 32)
CID = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Chain fixtures
# ---------------------------------------------------------------------------


def eth_chain() -> ChainRef:
    return ChainRef(
        namespace="eip155",
        network="ethereum-mainnet",
        chain_id="1",
        genesis_hash=ETH_GENESIS,
    )


def btc_chain() -> ChainRef:
    return ChainRef(
        namespace="bip122",
        network="bitcoin-mainnet",
        chain_id="000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f",
        genesis_hash=BTC_GENESIS,
    )


def sol_chain() -> ChainRef:
    return ChainRef(
        namespace="solana",
        network="mainnet-beta",
        chain_id="mainnet-beta",
        genesis_hash=SOL_GENESIS,
    )


def _provenance(chain: ChainRef, scope: str, provider: str = "fixture-rpc") -> Provenance:
    return Provenance(
        provider=provider,
        provider_kind="json-rpc",
        request_id=f"req-{chain.network}",
        scope=scope,
        observed_at=NOW,
        raw_payload=RawPayloadRef(
            digest=DIGEST,
            cid=CID,
            media_type="application/json",
            byte_length=64,
        ),
    )


def eth_fixtures(chain: ChainRef | None = None) -> list[object]:
    chain = chain or eth_chain()
    prov = _provenance(chain, "wallet:0xabc/eth")
    block = BlockRecord(
        chain=chain,
        provenance=prov,
        ledger_position=LedgerPosition(sequence=100, hash="0xethblock100"),
        finality=Finality.CONFIRMED,
        block_hash="0xethblock100",
        parent_hash="0xethblock99",
        block_time=NOW,
        transaction_count=2,
    )
    tx = TransactionRecord(
        chain=chain,
        provenance=prov,
        ledger_position=LedgerPosition(
            sequence=100, hash="0xethblock100", transaction_index=0
        ),
        finality=Finality.CONFIRMED,
        transaction_hash="0xethtx01",
        status=TransactionStatus.SUCCEEDED,
        participants=(AccountRef(chain, "0xabc", AccountKind.ADDRESS),),
    )
    transfer = TransferRecord(
        chain=chain,
        provenance=prov,
        ledger_position=LedgerPosition(
            sequence=100, hash="0xethblock100", transaction_index=0
        ),
        finality=Finality.CONFIRMED,
        transaction_hash="0xethtx01",
        transfer_index=0,
        asset=AssetRef(
            chain,
            asset_namespace="slip44",
            asset_reference="60",
            decimals=18,
            kind=AssetKind.NATIVE,
            symbol="ETH",
        ),
        amount=ExactAmount(base_units="1000000000000000000", decimals=18),
        source_account=AccountRef(chain, "0xabc", AccountKind.ADDRESS),
        destination_account=AccountRef(chain, "0xdef", AccountKind.ADDRESS),
        transfer_kind=TransferKind.NATIVE,
    )
    event = ContractEventRecord(
        chain=chain,
        provenance=prov,
        ledger_position=LedgerPosition(
            sequence=100,
            hash="0xethblock100",
            transaction_index=0,
            event_index=0,
        ),
        finality=Finality.CONFIRMED,
        transaction_hash="0xethtx01",
        event_index=0,
        contract=AccountRef(chain, "0xcontract", AccountKind.CONTRACT),
        event_signature="Transfer(address,address,uint256)",
        topics=("0xtopic0",),
        data_ref=RawPayloadRef(
            digest=DIGEST,
            cid=CID,
            media_type="application/octet-stream",
            byte_length=32,
        ),
    )
    return [block, tx, transfer, event]


def btc_fixtures(chain: ChainRef | None = None) -> list[object]:
    chain = chain or btc_chain()
    prov = _provenance(chain, "wallet:bc1qtest/btc", provider="bitcoin-rpc")
    block = BlockRecord(
        chain=chain,
        provenance=prov,
        ledger_position=LedgerPosition(sequence=800_000, hash="0xbtcblock800000"),
        finality=Finality.FINALIZED,
        block_hash="0xbtcblock800000",
        parent_hash="0xbtcblock799999",
        block_time=NOW,
        transaction_count=1,
    )
    utxo = UTXORecord(
        chain=chain,
        provenance=prov,
        ledger_position=LedgerPosition(
            sequence=800_000, hash="0xbtcblock800000", transaction_index=0
        ),
        finality=Finality.FINALIZED,
        transaction_hash="0xbtctx01",
        output_index=0,
        asset=AssetRef(
            chain,
            asset_namespace="slip44",
            asset_reference="0",
            decimals=8,
            kind=AssetKind.NATIVE,
            symbol="BTC",
        ),
        amount=ExactAmount(base_units="50000000", decimals=8),
        owner=AccountRef(chain, "bc1qtest", AccountKind.ADDRESS),
    )
    return [block, utxo]


def sol_fixtures(chain: ChainRef | None = None) -> list[object]:
    chain = chain or sol_chain()
    prov = _provenance(chain, "wallet:SoLtest/sol", provider="solana-rpc")
    block = BlockRecord(
        chain=chain,
        provenance=prov,
        ledger_position=LedgerPosition(sequence=250_000_000, hash="solSlotHash250m"),
        finality=Finality.FINALIZED,
        block_hash="solSlotHash250m",
        parent_hash="solSlotHash249m",
        block_time=NOW,
        transaction_count=1,
    )
    tx = TransactionRecord(
        chain=chain,
        provenance=prov,
        ledger_position=LedgerPosition(
            sequence=250_000_000, hash="solSlotHash250m", transaction_index=0
        ),
        finality=Finality.FINALIZED,
        transaction_hash="solTxSignature01",
        status=TransactionStatus.SUCCEEDED,
        participants=(AccountRef(chain, "SoLtest", AccountKind.ADDRESS),),
    )
    return [block, tx]


# ---------------------------------------------------------------------------
# Fixture providers / normalizer
# ---------------------------------------------------------------------------


class IdentityNormalizer:
    """Pass-through normalizer for pre-built ledger records."""

    def __init__(self, chain: ChainRef) -> None:
        self.chain = chain
        self.capabilities = Capabilities(
            provider="fixture-normalizer",
            chain_namespaces=frozenset({chain.namespace}),
            features=frozenset(
                {
                    Capability.WALLET_HISTORY,
                    Capability.LEDGER_RANGE,
                    Capability.DATASET_EXPORT,
                }
            ),
        )

    def normalize(
        self, records: Sequence[object], *, context: OperationContext
    ) -> list[object]:
        context.check_active()
        return list(records)


class FixtureWalletProvider:
    """Yields prebuilt multi-page native batches for one chain fixture set."""

    def __init__(self, pages: Sequence[Sequence[object]], chain: ChainRef) -> None:
        self._pages = [tuple(page) for page in pages]
        self.chain = chain
        self.capabilities = Capabilities(
            provider="fixture-rpc",
            chain_namespaces=frozenset({chain.namespace}),
            features=frozenset(
                {
                    Capability.WALLET_HISTORY,
                    Capability.LEDGER_RANGE,
                    Capability.RAW_PAYLOADS,
                }
            ),
        )

    async def validate_address(
        self, address: str, *, context: OperationContext
    ) -> object:
        context.check_active()
        return address

    def ingest_wallet(
        self, request: BoundedRequest
    ) -> AsyncIterator[RecordBatch]:
        return self._ingest(request)

    def ingest_ledger(
        self, request: BoundedRequest
    ) -> AsyncIterator[RecordBatch]:
        return self._ingest(request)

    async def _ingest(
        self, request: BoundedRequest
    ) -> AsyncIterator[RecordBatch]:
        request.context.check_active()
        for index, page in enumerate(self._pages):
            next_cursor = f"page-{index + 1}" if index + 1 < len(self._pages) else None
            yield RecordBatch(
                records=page,
                next_cursor=next_cursor,
                response_bytes=128,
            )


@pytest.fixture(autouse=True)
def _reset_shadow_singletons() -> None:
    reset_api_shadow_store()
    reset_registry_shadow_store()
    set_api_shadow_enabled(True)
    yield
    reset_api_shadow_store()
    reset_registry_shadow_store()


@pytest.fixture
def context() -> OperationContext:
    return OperationContext(
        request_id="shadow-ledger-test-1",
        limits=RequestLimits(
            max_items=100,
            max_pages=10,
            max_requests=20,
            max_response_bytes=64 * 1024,
        ),
    )


# ---------------------------------------------------------------------------
# Acceptance: chain fixtures match JSONL and DB projections
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "chain_factory,fixture_factory,scope",
    [
        (eth_chain, eth_fixtures, "wallet:0xabc/eth"),
        (btc_chain, btc_fixtures, "wallet:bc1qtest/btc"),
        (sol_chain, sol_fixtures, "wallet:SoLtest/sol"),
    ],
    ids=["ethereum", "bitcoin", "solana"],
)
def test_chain_fixtures_match_jsonl_and_db_projections(
    tmp_path: Path,
    context: OperationContext,
    chain_factory,
    fixture_factory,
    scope: str,
) -> None:
    chain = chain_factory()
    records = fixture_factory(chain)
    shadow = open_wallet_store(scope=f"shadow:{scope}", auto_recover=True)
    sink = StreamingDatasetSink(
        scope=scope,
        output_dir=tmp_path / chain.network,
        raw_payload_policy=RawPayloadPolicy.OMITTED,
        shadow_store=shadow,
    )
    _run(
        sink.write(
            RecordBatch(records=tuple(records), response_bytes=64),
            context=context,
        )
    )
    commit = _run(sink.commit(None, context=context))
    assert commit.record_count == len(records)

    jsonl_rows = sink.read_jsonl_records()
    assert len(jsonl_rows) == len(records)

    parity = compare_jsonl_db_projections(jsonl_rows, shadow)
    assert parity.matched, parity.to_dict()
    assert sink.last_parity is not None
    assert sink.last_parity.matched

    # Deterministic IDs: every fixture record_id must appear in DB fact tables.
    for record in records:
        rid = record_identity(record)
        assert shadow.get_record(rid) is not None
        # Projection helper must produce the same record_id primary key.
        projected = project_ledger_record_rows(record)
        found = False
        for table, rows in projected.items():
            if table in {
                "blocks",
                "transactions",
                "transfers",
                "utxos",
                "token_accounts",
                "contract_events",
            }:
                for row in rows:
                    if row.get("record_id") == rid:
                        found = True
        assert found, f"projection missing record_id {rid}"

    # Encrypted object refs may exist (CID/digest only) when fixtures carry refs.
    assert_shadow_catalog_excludes_secrets(shadow)


def test_pipeline_ingest_shadows_all_chain_fixtures(tmp_path: Path) -> None:
    """End-to-end pipeline dual-write for multi-chain fixture pages."""

    results = []
    for chain_factory, fixture_factory, scope in (
        (eth_chain, eth_fixtures, "wallet:0xabc/eth"),
        (btc_chain, btc_fixtures, "wallet:bc1qtest/btc"),
        (sol_chain, sol_fixtures, "wallet:SoLtest/sol"),
    ):
        chain = chain_factory()
        records = fixture_factory(chain)
        shadow = open_wallet_store(scope=f"pipe:{scope}", auto_recover=True)
        provider = FixtureWalletProvider([records], chain)
        processor = WalletLedgerProcessor(
            chain=chain,
            wallet_provider=provider,
            ledger_provider=provider,
            normalizer=IdentityNormalizer(chain),
            shadow_store=shadow,
            provider_name="fixture-rpc",
            normalizer_version="fixture-normalizer@1.0.0",
        )
        context = OperationContext(
            request_id=f"pipe-{chain.network}",
            limits=RequestLimits(max_items=50, max_pages=5, max_requests=10),
        )
        request = BoundedRequest(scope=scope, context=context)
        out = tmp_path / chain.network
        receipt = _run(
            processor.ingest_wallet(
                request,
                export_dir=str(out),
                observed_anchor=HashAnchor(
                    sequence=records[0].ledger_position.sequence,
                    block_hash=records[0].ledger_position.hash,
                ),
            )
        )
        assert receipt.status is RunStatus.COMPLETE
        assert receipt.records_accepted == len(records)
        assert receipt.checkpoint_advanced
        assert processor.shadow_store is shadow
        assert processor.last_sink is not None
        jsonl = processor.last_sink.read_jsonl_records()
        parity = compare_jsonl_db_projections(jsonl, shadow)
        assert parity.matched, parity.to_dict()
        results.append((chain.network, len(records), parity.matched))

    assert len(results) == 3
    assert all(matched for _, _, matched in results)


# ---------------------------------------------------------------------------
# Acceptance: checkpoint / reorg / deterministic-ID parity
# ---------------------------------------------------------------------------


def test_checkpoint_reorg_and_deterministic_id_parity(
    tmp_path: Path, context: OperationContext
) -> None:
    chain = eth_chain()
    records = eth_fixtures(chain)
    shadow = open_wallet_store(scope="shadow:checkpoint-parity", auto_recover=True)
    checkpoints = InMemoryCheckpointStore(shadow_store=shadow)
    provider = FixtureWalletProvider([records], chain)
    processor = WalletLedgerProcessor(
        chain=chain,
        wallet_provider=provider,
        ledger_provider=provider,
        normalizer=IdentityNormalizer(chain),
        checkpoint_store=checkpoints,
        shadow_store=shadow,
        provider_name="fixture-rpc",
        normalizer_version="fixture-normalizer@1.0.0",
    )
    scope = "wallet:0xabc/eth-checkpoint"
    request = BoundedRequest(scope=scope, context=context)
    receipt = _run(
        processor.ingest_wallet(
            request,
            export_dir=str(tmp_path / "eth-cp"),
            observed_anchor=HashAnchor(100, "0xethblock100"),
        )
    )
    assert receipt.checkpoint_advanced
    assert receipt.checkpoint_after is not None

    identity = processor.identity_for(scope)
    # Authority tip matches shadow tip (checkpoint_id / anchor / revision).
    parity = checkpoints.checkpoint_parity(identity.key)
    assert parity["matched"] is True, parity

    # Deterministic checkpoint identity key is stable across rebuilds.
    identity_again = CheckpointIdentity(
        chain=chain,
        provider="fixture-rpc",
        scope=scope,
        normalized_schema_major=1,
        normalizer_version="fixture-normalizer@1.0.0",
    )
    assert identity.key == identity_again.key
    assert identity.key == receipt.checkpoint_after.identity.key

    # Fingerprint of durable checkpoint content is stable for same fields.
    fp = checkpoint_content_fingerprint(receipt.checkpoint_after)
    rebuilt = build_checkpoint(
        identity,
        sequence=receipt.checkpoint_after.anchor.sequence,
        block_hash=receipt.checkpoint_after.anchor.block_hash,
        revision=receipt.checkpoint_after.revision,
        safety_depth=receipt.checkpoint_after.safety_depth,
        continuation_token=receipt.checkpoint_after.continuation_token,
        sink_commit_id=receipt.checkpoint_after.sink_commit_id,
        prior_history=receipt.checkpoint_after.history[:-1],
        metadata=receipt.checkpoint_after.metadata,
    )
    assert rebuilt.anchor.matches(receipt.checkpoint_after.anchor)
    assert rebuilt.identity.key == receipt.checkpoint_after.identity.key
    assert checkpoint_content_fingerprint(rebuilt) == fp

    # Reorg: orphan the tip block and rewind to ancestor.
    tip = records[0]
    assert isinstance(tip, BlockRecord)
    correction = OrphanCorrection(
        record_id=tip.record_id,
        prior_finality=Finality.CONFIRMED,
        new_finality=Finality.ORPHANED,
        orphaned_anchor=HashAnchor(100, "0xethblock100"),
        ancestor_anchor=HashAnchor(99, "0xethblock99"),
        tombstone=True,
    )
    decision = ReorgDecision(
        kind=ReorgKind.SHALLOW,
        checkpoint_anchor=HashAnchor(100, "0xethblock100"),
        observed_anchor=HashAnchor(101, "0xethblock101alt"),
        common_ancestor=HashAnchor(99, "0xethblock99"),
        orphaned_anchors=(HashAnchor(100, "0xethblock100"),),
        corrections=(correction,),
        rewind_sequence=99,
        reason="fixture shallow reorg",
    )
    rewound = build_checkpoint(
        identity,
        sequence=99,
        block_hash="0xethblock99",
        revision=new_revision(),
        prior_history=receipt.checkpoint_after.history,
        sink_commit_id=receipt.checkpoint_after.sink_commit_id,
    )
    reorg_result = _run(
        processor.apply_reorg(
            decision,
            provenance=_provenance(chain, scope),
            identity=identity,
            rewound=rewound,
            expected_revision=receipt.checkpoint_after.revision,
            context=context,
            reorg_id="reorg:fixture-1",
        )
    )
    assert reorg_result["checkpoint_advanced"] is True
    assert reorg_result.get("reorg_id")

    # Reorg history retained on shadow (never overwritten).
    reorgs = shadow.list_reorgs()
    assert len(reorgs) >= 1
    assert any(r.get("reorg_id") for r in reorgs)

    # Finality transition shadowed for the orphaned block.
    transitions = shadow.list_finality_transitions(record_id=tip.record_id)
    assert transitions
    assert transitions[-1]["finality"] == Finality.ORPHANED.value

    loaded = _run(checkpoints.load(identity.key, context=context))
    assert loaded is not None
    assert loaded.anchor.sequence == 99
    assert loaded.anchor.block_hash == "0xethblock99"

    post_reorg_parity = checkpoints.checkpoint_parity(identity.key)
    assert post_reorg_parity["matched"] is True, post_reorg_parity


# ---------------------------------------------------------------------------
# Acceptance: secrets / signing / raw bytes never enter DuckDB
# ---------------------------------------------------------------------------


def test_secrets_signing_and_raw_bytes_never_enter_duckdb(
    tmp_path: Path, context: OperationContext
) -> None:
    chain = eth_chain()
    records = eth_fixtures(chain)
    shadow = open_wallet_store(scope="shadow:secrets", auto_recover=True)
    sink = StreamingDatasetSink(
        scope="wallet:secret-safe",
        output_dir=tmp_path / "secret-safe",
        shadow_store=shadow,
    )
    _run(
        sink.write(
            RecordBatch(records=tuple(records), response_bytes=32),
            context=context,
        )
    )
    _run(sink.commit(None, context=context))
    assert_shadow_catalog_excludes_secrets(shadow)

    # Direct projection rejects secret-shaped metadata on public rows.
    from ipfs_datasets_py.processors.wallets.models import ensure_secret_safe

    with pytest.raises(Exception):
        ensure_secret_safe({"api_secret": "super-secret-value-12345"})

    # Unrestricted raw body must not be accepted on encrypted_object_refs.
    # Non-RawPayloadRef objects fail closed at the type gate; subclass smuggling
    # is covered in test_put_encrypted_object_ref_rejects_raw_body_field.
    class _BadRef:
        digest = DIGEST
        cid = CID
        media_type = "application/json"
        byte_length = 4
        body = b"raw-secret-bytes"

    with pytest.raises(InvalidRequestError, match="RawPayloadRef|must not carry payload"):
        shadow.put_encrypted_object_ref(
            _BadRef(),  # type: ignore[arg-type]
            chain=chain,
            provenance=_provenance(chain, "wallet:secret-safe"),
            finality=Finality.OBSERVED,
        )


def test_put_encrypted_object_ref_rejects_raw_body_field(
    context: OperationContext,
) -> None:
    chain = eth_chain()
    shadow = open_wallet_store(scope="shadow:raw-reject", auto_recover=True)
    prov = _provenance(chain, "wallet:raw-reject")

    # DuckDB store rejects non-RawPayloadRef objects before any row is written.
    with pytest.raises(InvalidRequestError, match="RawPayloadRef"):
        shadow.put_encrypted_object_ref(
            {"digest": DIGEST, "body": b"smuggled-bytes"},  # type: ignore[arg-type]
            chain=chain,
            provenance=prov,
            finality=Finality.OBSERVED,
        )

    # Legitimate CID/digest-only ref is accepted and remains byte-free.
    row = shadow.put_encrypted_object_ref(
        RawPayloadRef(
            digest=DIGEST,
            cid=CID,
            media_type="application/json",
            byte_length=12,
        ),
        chain=chain,
        provenance=prov,
        finality=Finality.OBSERVED,
    )
    assert "digest" in row
    assert "body" not in row
    assert "raw_payload" not in row
    # Catalog scan must not see raw payload bodies after a legal ref write.
    refs = shadow.list_records("encrypted_object_refs")
    assert refs
    for ref_row in refs:
        for key, value in ref_row.items():
            assert not isinstance(value, (bytes, bytearray, memoryview))
            assert "secret" not in str(key).casefold()
            assert key not in {"body", "raw_payload", "ciphertext", "plaintext"}
    assert_shadow_catalog_excludes_secrets(shadow)


# ---------------------------------------------------------------------------
# Injection paths: storage, checkpoints, pipeline, API, registry
# ---------------------------------------------------------------------------


def test_api_and_registry_inject_shadow_store(tmp_path: Path) -> None:
    chain = eth_chain()
    records = eth_fixtures(chain)
    shadow = open_wallet_store(scope="shadow:api-registry", auto_recover=True)
    provider = FixtureWalletProvider([records], chain)
    processor = build_wallet_ledger_processor_from_options(
        chain=chain,
        wallet_provider=provider,
        ledger_provider=provider,
        normalizer=IdentityNormalizer(chain),
        options={
            "shadow_store": shadow,
            "provider_name": "fixture-rpc",
            "normalizer_version": "fixture-normalizer@1.0.0",
        },
    )
    assert processor.shadow_store is shadow

    api = WalletProcessorAPI(processor=processor, shadow_store=shadow, shadow=True)
    assert api.shadow_store is shadow
    assert api.shadow_mode == "shadow"

    context = OperationContext(
        request_id="api-shadow-1",
        limits=RequestLimits(max_items=50, max_pages=5, max_requests=10),
    )
    request = BoundedRequest(scope="wallet:0xabc/api", context=context)
    receipt = _run(
        processor.ingest_wallet(
            request,
            export_dir=str(tmp_path / "api"),
            observed_anchor=HashAnchor(100, "0xethblock100"),
        )
    )
    assert receipt.status is RunStatus.COMPLETE
    parity = compare_jsonl_db_projections(
        processor.last_sink.read_jsonl_records(), shadow
    )
    assert parity.matched, parity.to_dict()

    # Registry option resolution.
    resolved = resolve_shadow_store_from_options({"shadow_store": shadow})
    assert resolved is shadow
    assert resolve_shadow_store_from_options({"shadow": False}) is None
    assert resolve_shadow_store_from_options({"enable_shadow": True}) is not None

    registry = WalletProcessorRegistry(default_shadow=False, shadow_store=shadow)
    assert registry.default_shadow_store is shadow

    # attach_shadow_ledger is idempotent for pipeline processors.
    attach_shadow_ledger(processor, shadow)
    assert processor.shadow_store is shadow


def test_shadow_write_failure_fails_closed(
    tmp_path: Path, context: OperationContext
) -> None:
    """When shadow is enabled, dual-write errors must not silently drop."""

    class _BrokenShadow:
        async def write(self, batch, *, context):  # noqa: ANN001
            raise RuntimeError("shadow unavailable")

        async def commit(self, manifest, *, context):  # noqa: ANN001
            raise RuntimeError("shadow unavailable")

        async def abort(self, *, context):  # noqa: ANN001
            return None

    chain = eth_chain()
    sink = StreamingDatasetSink(
        scope="wallet:broken",
        output_dir=tmp_path / "broken",
        shadow_store=_BrokenShadow(),
    )
    with pytest.raises(DatasetSinkError, match="shadow ledger write failed"):
        _run(
            sink.write(
                RecordBatch(records=tuple(eth_fixtures(chain)), response_bytes=8),
                context=context,
            )
        )
