"""Unit tests for transactional DuckDB wallet store and durable checkpoints (DQK-036).

Acceptance coverage:

* Crash recovery cannot skip or duplicate ledger records
* Checkpoint CAS rejects stale ingesters
* Reorg history is retained instead of overwritten
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys

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

import pytest

from ipfs_datasets_py.processors.wallets.checkpoints import (
    CheckpointIdentity,
    HashAnchor,
    build_checkpoint,
    new_revision,
)
from ipfs_datasets_py.processors.wallets.duckdb_schema import (
    DUCKDB_WALLET_SCHEMA_VERSION,
    WALLET_CATALOG_TABLES,
)
from ipfs_datasets_py.processors.wallets.duckdb_storage import (
    DUCKDB_WALLET_STORE_INTERFACE,
    DUCKDB_WALLET_STORE_SCHEMA_VERSION,
    DuckDBWalletStore,
    StageBatchStatus,
    open_wallet_store,
)
from ipfs_datasets_py.processors.wallets.errors import (
    CheckpointError,
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
    ExactAmount,
    Finality,
    LedgerPosition,
    Provenance,
    RawPayloadRef,
    TransferKind,
    TransferRecord,
)
from ipfs_datasets_py.processors.wallets.protocols import (
    OperationContext,
    RecordBatch,
    RequestLimits,
)


NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
DIGEST = "sha256:" + ("cd" * 32)
GENESIS = "0xd4e56740f876aef8c010b86a40d5f56745a118d0906a34e69aec8c0db1cb8fa3"


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def chain() -> ChainRef:
    return ChainRef(
        namespace="eip155",
        network="ethereum-mainnet",
        chain_id="1",
        genesis_hash=GENESIS,
    )


@pytest.fixture
def provenance() -> Provenance:
    return Provenance(
        provider="fixture-rpc",
        provider_kind="json-rpc",
        request_id="req-storage-001",
        scope="wallet:0xabc",
        observed_at=NOW,
        raw_payload=RawPayloadRef(
            digest=DIGEST,
            cid="bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
            media_type="application/json",
            byte_length=128,
        ),
    )


@pytest.fixture
def identity(chain: ChainRef) -> CheckpointIdentity:
    return CheckpointIdentity(
        chain=chain,
        provider="fixture-rpc",
        scope="wallet:0xabc/transfers",
        normalized_schema_major=1,
        normalizer_version="ethereum-normalizer@1.0.0",
    )


@pytest.fixture
def context() -> OperationContext:
    return OperationContext(
        request_id="duckdb-storage-test-1",
        limits=RequestLimits(
            max_items=100,
            max_pages=10,
            max_requests=20,
            max_response_bytes=64 * 1024,
        ),
    )


@pytest.fixture
def store() -> DuckDBWalletStore:
    return open_wallet_store(scope="wallet:test", auto_recover=True)


def _block(
    chain: ChainRef,
    provenance: Provenance,
    *,
    sequence: int,
    block_hash: str,
    parent_hash: str | None = None,
    finality: Finality = Finality.OBSERVED,
) -> BlockRecord:
    return BlockRecord(
        chain=chain,
        provenance=provenance,
        ledger_position=LedgerPosition(sequence=sequence, hash=block_hash),
        finality=finality,
        block_hash=block_hash,
        parent_hash=parent_hash or f"0xparent{sequence - 1}",
        block_time=NOW,
        transaction_count=1,
    )


def _transfer(
    chain: ChainRef,
    provenance: Provenance,
    *,
    tx_hash: str,
    transfer_index: int = 0,
    sequence: int = 100,
    finality: Finality = Finality.CONFIRMED,
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
        provenance=provenance,
        ledger_position=LedgerPosition(
            sequence=sequence, hash=f"0xblock{sequence}", transaction_index=0
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


# ---------------------------------------------------------------------------
# Interface / catalog
# ---------------------------------------------------------------------------


def test_store_interface_pins(store: DuckDBWalletStore) -> None:
    assert store.interface == DUCKDB_WALLET_STORE_INTERFACE
    assert store.schema_version == DUCKDB_WALLET_STORE_SCHEMA_VERSION
    assert store.catalog_tables() == WALLET_CATALOG_TABLES
    assert store.catalog_schema_version == DUCKDB_WALLET_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Idempotent batches
# ---------------------------------------------------------------------------


def test_write_and_commit_promotes_ledger_rows(
    store: DuckDBWalletStore,
    chain: ChainRef,
    provenance: Provenance,
    context: OperationContext,
) -> None:
    blocks = [
        _block(chain, provenance, sequence=1, block_hash="0x01"),
        _block(chain, provenance, sequence=2, block_hash="0x02", parent_hash="0x01"),
    ]
    receipt = _run(
        store.write(RecordBatch(records=tuple(blocks)), context=context)
    )
    assert receipt.accepted_count == 2
    assert receipt.duplicate_count == 0
    assert store.count_records("blocks") == 0  # staged, not committed

    commit = _run(store.commit(None, context=context))
    assert commit.record_count == 2
    assert store.count_records("blocks") == 2
    assert store.get_record(blocks[0].record_id) is not None
    assert store.get_record(blocks[1].record_id) is not None


def test_duplicate_record_id_is_idempotent_within_and_across_batches(
    store: DuckDBWalletStore,
    chain: ChainRef,
    provenance: Provenance,
    context: OperationContext,
) -> None:
    block = _block(chain, provenance, sequence=5, block_hash="0x05")
    first = _run(
        store.write(RecordBatch(records=(block, block)), context=context)
    )
    assert first.accepted_count == 1
    assert first.duplicate_count == 1

    _run(store.commit(None, context=context))
    assert store.count_records("blocks") == 1

    second = _run(store.write(RecordBatch(records=(block,)), context=context))
    assert second.accepted_count == 0
    assert second.duplicate_count == 1
    _run(store.commit(None, context=context))
    assert store.count_records("blocks") == 1


def test_idempotency_key_replays_same_receipt(
    store: DuckDBWalletStore,
    chain: ChainRef,
    provenance: Provenance,
    context: OperationContext,
) -> None:
    block = _block(chain, provenance, sequence=7, block_hash="0x07")
    batch = RecordBatch(records=(block,))
    a = _run(
        store.write(batch, context=context, idempotency_key="ingest-page-7")
    )
    b = _run(
        store.write(batch, context=context, idempotency_key="ingest-page-7")
    )
    assert a.write_id == b.write_id
    assert a.content_digest == b.content_digest
    assert a.accepted_count == 1
    # Only one stage open despite two write calls.
    assert store.open_stage_count() == 1


def test_idempotency_key_rejects_content_mismatch(
    store: DuckDBWalletStore,
    chain: ChainRef,
    provenance: Provenance,
    context: OperationContext,
) -> None:
    a = _block(chain, provenance, sequence=1, block_hash="0x01")
    b = _block(chain, provenance, sequence=2, block_hash="0x02")
    _run(
        store.write(
            RecordBatch(records=(a,)), context=context, idempotency_key="same-key"
        )
    )
    with pytest.raises(DatasetSinkError, match="idempotency key reused"):
        _run(
            store.write(
                RecordBatch(records=(b,)),
                context=context,
                idempotency_key="same-key",
            )
        )


def test_abort_discards_staged_without_durable_rows(
    store: DuckDBWalletStore,
    chain: ChainRef,
    provenance: Provenance,
    context: OperationContext,
) -> None:
    block = _block(chain, provenance, sequence=9, block_hash="0x09")
    _run(store.write(RecordBatch(records=(block,)), context=context))
    _run(store.abort(context=context))
    assert store.count_records("blocks") == 0
    assert store.is_aborted
    with pytest.raises(DatasetSinkError, match="aborted"):
        _run(store.write(RecordBatch(records=(block,)), context=context))
    store.reset_for_resume()
    receipt = _run(store.write(RecordBatch(records=(block,)), context=context))
    assert receipt.accepted_count == 1
    _run(store.commit(None, context=context))
    assert store.count_records("blocks") == 1


# ---------------------------------------------------------------------------
# Acceptance: crash recovery cannot skip or duplicate ledger records
# ---------------------------------------------------------------------------


def test_crash_mid_commit_recovery_does_not_skip_or_duplicate(
    store: DuckDBWalletStore,
    chain: ChainRef,
    provenance: Provenance,
    context: OperationContext,
) -> None:
    """Simulate crash after COMMITTING fence; recover must promote all rows once."""

    blocks = [
        _block(chain, provenance, sequence=i, block_hash=f"0x{i:02x}")
        for i in range(1, 6)
    ]
    receipt = _run(
        store.write(RecordBatch(records=tuple(blocks)), context=context)
    )
    assert receipt.accepted_count == 5
    assert store.count_records("blocks") == 0

    marked = store.simulate_crash_before_commit_finalize()
    assert marked
    assert store.count_records("blocks") == 0  # not yet durable

    recovered = store.recover()
    assert recovered["recovered_commits"] == 1
    assert store.count_records("blocks") == 5

    # Replaying recovery is a no-op (already committed stages).
    recovered_again = store.recover()
    assert recovered_again["recovered_commits"] == 0
    assert store.count_records("blocks") == 5

    # Re-ingesting the same pages cannot create duplicates.
    again = _run(
        store.write(RecordBatch(records=tuple(blocks)), context=context)
    )
    assert again.accepted_count == 0
    assert again.duplicate_count == 5
    _run(store.commit(None, context=context))
    assert store.count_records("blocks") == 5


def test_crash_before_commit_aborts_open_stages_without_skipping_committed(
    store: DuckDBWalletStore,
    chain: ChainRef,
    provenance: Provenance,
    context: OperationContext,
) -> None:
    committed = _block(chain, provenance, sequence=1, block_hash="0x01")
    open_block = _block(chain, provenance, sequence=2, block_hash="0x02")

    _run(store.write(RecordBatch(records=(committed,)), context=context))
    _run(store.commit(None, context=context))
    assert store.count_records("blocks") == 1

    _run(store.write(RecordBatch(records=(open_block,)), context=context))
    assert store.open_stage_count() == 1

    recovered = store.recover()
    assert recovered["recovered_aborts"] == 1
    assert store.count_records("blocks") == 1  # only the committed row
    assert store.get_record(committed.record_id) is not None
    assert store.get_record(open_block.record_id) is None

    # After abort recovery, the open block can be ingested cleanly (no skip).
    store.reset_for_resume()
    receipt = _run(
        store.write(RecordBatch(records=(open_block,)), context=context)
    )
    assert receipt.accepted_count == 1
    _run(store.commit(None, context=context))
    assert store.count_records("blocks") == 2


def test_partial_multi_batch_commit_recovery_is_idempotent(
    store: DuckDBWalletStore,
    chain: ChainRef,
    provenance: Provenance,
    context: OperationContext,
) -> None:
    batch_a = [
        _block(chain, provenance, sequence=10, block_hash="0x0a"),
        _block(chain, provenance, sequence=11, block_hash="0x0b"),
    ]
    batch_b = [
        _block(chain, provenance, sequence=12, block_hash="0x0c"),
    ]
    _run(store.write(RecordBatch(records=tuple(batch_a)), context=context))
    _run(store.write(RecordBatch(records=tuple(batch_b)), context=context))
    assert store.open_stage_count() == 2

    store.simulate_crash_before_commit_finalize()
    store.recover()
    assert store.count_records("blocks") == 3

    # Second recover must not invent extra rows.
    store.recover()
    assert store.count_records("blocks") == 3
    ids = {r["record_id"] for r in store.list_records("blocks")}
    assert len(ids) == 3


# ---------------------------------------------------------------------------
# Acceptance: checkpoint CAS rejects stale ingesters
# ---------------------------------------------------------------------------


def test_checkpoint_cas_accepts_matching_revision(
    store: DuckDBWalletStore,
    identity: CheckpointIdentity,
    context: OperationContext,
) -> None:
    first = build_checkpoint(
        identity, sequence=1, block_hash="0x01", safety_depth=12
    )
    accepted = _run(
        store.compare_and_set(
            identity.key,
            expected_revision=None,
            checkpoint=first,
            context=context,
        )
    )
    assert accepted is True
    loaded = _run(store.load(identity.key, context=context))
    assert loaded is not None
    assert loaded.revision == first.revision
    assert loaded.anchor.block_hash == "0x01"


def test_checkpoint_cas_rejects_stale_ingester(
    store: DuckDBWalletStore,
    identity: CheckpointIdentity,
    context: OperationContext,
) -> None:
    first = build_checkpoint(
        identity, sequence=1, block_hash="0x01", safety_depth=12
    )
    assert _run(
        store.compare_and_set(
            identity.key,
            expected_revision=None,
            checkpoint=first,
            context=context,
        )
    )

    # Stale ingester still believes revision is None (or an old token).
    stale = build_checkpoint(
        identity,
        sequence=2,
        block_hash="0x02",
        safety_depth=12,
        prior_history=first.history,
    )
    rejected = _run(
        store.compare_and_set(
            identity.key,
            expected_revision=None,
            checkpoint=stale,
            context=context,
        )
    )
    assert rejected is False

    also_stale = build_checkpoint(
        identity,
        sequence=3,
        block_hash="0x03",
        safety_depth=12,
        prior_history=first.history,
    )
    rejected2 = _run(
        store.compare_and_set(
            identity.key,
            expected_revision="rev:not-the-current-one",
            checkpoint=also_stale,
            context=context,
        )
    )
    assert rejected2 is False

    # Tip remains at first successful CAS.
    loaded = _run(store.load(identity.key, context=context))
    assert loaded is not None
    assert loaded.revision == first.revision
    assert loaded.anchor.sequence == 1
    assert store.cas_attempts == 3
    assert store.cas_successes == 1
    assert store.stats()["cas_rejects"] == 2


def test_checkpoint_cas_advances_with_current_revision(
    store: DuckDBWalletStore,
    identity: CheckpointIdentity,
    context: OperationContext,
) -> None:
    first = build_checkpoint(
        identity, sequence=1, block_hash="0x01", safety_depth=12
    )
    _run(
        store.compare_and_set(
            identity.key,
            expected_revision=None,
            checkpoint=first,
            context=context,
        )
    )
    second = build_checkpoint(
        identity,
        sequence=2,
        block_hash="0x02",
        safety_depth=12,
        prior_history=first.history,
        sink_commit_id="commit:abc",
    )
    accepted = _run(
        store.compare_and_set(
            identity.key,
            expected_revision=first.revision,
            checkpoint=second,
            context=context,
        )
    )
    assert accepted is True
    loaded = _run(store.load(identity.key, context=context))
    assert loaded is not None
    assert loaded.anchor.sequence == 2
    assert loaded.sink_commit_id == "commit:abc"


def test_checkpoint_cas_rejects_identity_mismatch(
    store: DuckDBWalletStore,
    identity: CheckpointIdentity,
    context: OperationContext,
) -> None:
    other = CheckpointIdentity(
        chain=identity.chain,
        provider="other-rpc",
        scope=identity.scope,
        normalized_schema_major=identity.normalized_schema_major,
        normalizer_version=identity.normalizer_version,
    )
    cp = build_checkpoint(other, sequence=1, block_hash="0x01")
    with pytest.raises(CheckpointError, match="does not bind"):
        _run(
            store.compare_and_set(
                identity.key,
                expected_revision=None,
                checkpoint=cp,
                context=context,
            )
        )


def test_checkpoint_requires_hash_anchor(
    store: DuckDBWalletStore,
    identity: CheckpointIdentity,
    context: OperationContext,
) -> None:
    # build_checkpoint always requires hash; construct invalid via empty hash.
    with pytest.raises(InvalidRequestError):
        build_checkpoint(identity, sequence=1, block_hash="")


# ---------------------------------------------------------------------------
# Acceptance: reorg history is retained instead of overwritten
# ---------------------------------------------------------------------------


def test_reorg_history_is_retained_not_overwritten(
    store: DuckDBWalletStore,
    chain: ChainRef,
    provenance: Provenance,
    identity: CheckpointIdentity,
    context: OperationContext,
) -> None:
    # Seed durable blocks and a checkpoint tip.
    blocks = [
        _block(chain, provenance, sequence=1, block_hash="0x01"),
        _block(chain, provenance, sequence=2, block_hash="0x02", parent_hash="0x01"),
        _block(chain, provenance, sequence=3, block_hash="0x03", parent_hash="0x02"),
    ]
    _run(store.write(RecordBatch(records=tuple(blocks)), context=context))
    _run(store.commit(None, context=context))

    tip = build_checkpoint(
        identity,
        sequence=3,
        block_hash="0x03",
        safety_depth=12,
        prior_history=(
            HashAnchor(1, "0x01"),
            HashAnchor(2, "0x02"),
        ),
    )
    _run(
        store.compare_and_set(
            identity.key,
            expected_revision=None,
            checkpoint=tip,
            context=context,
        )
    )

    first_reorg = ReorgDecision(
        kind=ReorgKind.SHALLOW,
        checkpoint_anchor=HashAnchor(3, "0x03"),
        observed_anchor=HashAnchor(3, "0x03alt"),
        common_ancestor=HashAnchor(2, "0x02"),
        orphaned_anchors=(HashAnchor(3, "0x03"),),
        corrections=(
            OrphanCorrection(
                record_id=blocks[2].record_id,
                prior_finality=Finality.OBSERVED,
                new_finality=Finality.ORPHANED,
                orphaned_anchor=HashAnchor(3, "0x03"),
                ancestor_anchor=HashAnchor(2, "0x02"),
                tombstone=True,
            ),
        ),
        rewind_sequence=2,
        review_required=False,
        reason="shallow reorg depth=1",
    )
    row1 = store.record_reorg(first_reorg, chain=chain, provenance=provenance)
    assert row1["kind"] == "shallow"
    assert len(store.list_reorgs()) == 1

    # Second reorg on the same chain — prior history must remain.
    second_reorg = ReorgDecision(
        kind=ReorgKind.SHALLOW,
        checkpoint_anchor=HashAnchor(2, "0x02"),
        observed_anchor=HashAnchor(2, "0x02b"),
        common_ancestor=HashAnchor(1, "0x01"),
        orphaned_anchors=(HashAnchor(2, "0x02"),),
        corrections=(),
        rewind_sequence=1,
        review_required=False,
        reason="second shallow reorg",
    )
    row2 = store.record_reorg(second_reorg, chain=chain, provenance=provenance)
    assert row2["reorg_id"] != row1["reorg_id"]

    history = store.list_reorgs(chain_ref_id=chain.chain_ref_id)
    assert len(history) == 2
    reorg_ids = {h["reorg_id"] for h in history}
    assert row1["reorg_id"] in reorg_ids
    assert row2["reorg_id"] in reorg_ids
    # First reorg row payload is unchanged (not overwritten).
    original = next(h for h in history if h["reorg_id"] == row1["reorg_id"])
    assert original["reason"] == "shallow reorg depth=1"
    assert original["checkpoint_hash"] == "0x03"

    # Orphan correction applied as append-only finality transition.
    transitions = store.list_finality_transitions(record_id=blocks[2].record_id)
    assert len(transitions) >= 1
    assert transitions[-1]["finality"] == Finality.ORPHANED.value
    fact = store.get_record(blocks[2].record_id)
    assert fact is not None
    assert fact["finality"] == Finality.ORPHANED.value


def test_identical_reorg_id_is_idempotent_not_overwrite(
    store: DuckDBWalletStore,
    chain: ChainRef,
    provenance: Provenance,
) -> None:
    decision = ReorgDecision(
        kind=ReorgKind.DEEP,
        checkpoint_anchor=HashAnchor(100, "0x64"),
        observed_anchor=HashAnchor(100, "0x64b"),
        common_ancestor=None,
        orphaned_anchors=(),
        corrections=(),
        rewind_sequence=None,
        review_required=True,
        reason="deep reorg review",
    )
    first = store.record_reorg(
        decision, chain=chain, provenance=provenance, reorg_id="reorg:fixed-1"
    )
    second = store.record_reorg(
        decision, chain=chain, provenance=provenance, reorg_id="reorg:fixed-1"
    )
    assert first["reorg_id"] == second["reorg_id"]
    assert len(store.list_reorgs()) == 1
    assert store.stats()["reorgs"] == 1


def test_checkpoint_history_retained_across_cas(
    store: DuckDBWalletStore,
    identity: CheckpointIdentity,
    context: OperationContext,
) -> None:
    history_limit_store = open_wallet_store(history_limit=16)
    revs: list[str] = []
    prior: tuple[HashAnchor, ...] = ()
    for seq in range(1, 4):
        cp = build_checkpoint(
            identity,
            sequence=seq,
            block_hash=f"0x{seq:02x}",
            prior_history=prior,
        )
        expected = None if not revs else revs[-1]
        ok = _run(
            history_limit_store.compare_and_set(
                identity.key,
                expected_revision=expected,
                checkpoint=cp,
                context=context,
            )
        )
        assert ok
        revs.append(cp.revision)
        prior = cp.history

    hist = history_limit_store.checkpoint_history(identity.key)
    assert len(hist) == 3
    sequences = [h["anchor_sequence"] for h in hist]
    assert sequences == [1, 2, 3]
    # Catalog also retains each checkpoint_id row.
    assert history_limit_store.count_records("checkpoints") == 3


def test_replace_after_rewind_uses_cas(
    store: DuckDBWalletStore,
    identity: CheckpointIdentity,
    context: OperationContext,
) -> None:
    tip = build_checkpoint(
        identity,
        sequence=5,
        block_hash="0x05",
        prior_history=(
            HashAnchor(3, "0x03"),
            HashAnchor(4, "0x04"),
        ),
    )
    _run(
        store.compare_and_set(
            identity.key,
            expected_revision=None,
            checkpoint=tip,
            context=context,
        )
    )
    rewound = build_checkpoint(
        identity,
        sequence=3,
        block_hash="0x03",
        prior_history=(HashAnchor(3, "0x03"),),
        revision=new_revision(),
    )
    # Stale expected revision fails.
    assert (
        _run(
            store.replace_after_rewind(
                identity,
                expected_revision="rev:stale",
                rewound=rewound,
                context=context,
            )
        )
        is False
    )
    ok = _run(
        store.replace_after_rewind(
            identity,
            expected_revision=tip.revision,
            rewound=rewound,
            context=context,
        )
    )
    assert ok is True
    loaded = _run(store.load(identity.key, context=context))
    assert loaded is not None
    assert loaded.anchor.sequence == 3
    # Prior tips still in checkpoint history.
    assert len(store.checkpoint_history(identity.key)) == 2


# ---------------------------------------------------------------------------
# Finality transitions
# ---------------------------------------------------------------------------


def test_finality_transition_append_only_and_state_machine(
    store: DuckDBWalletStore,
    chain: ChainRef,
    provenance: Provenance,
    context: OperationContext,
) -> None:
    block = _block(
        chain, provenance, sequence=1, block_hash="0x01", finality=Finality.OBSERVED
    )
    _run(store.write(RecordBatch(records=(block,)), context=context))
    _run(store.commit(None, context=context))

    t1 = store.apply_finality_transition(
        record_id=block.record_id,
        target=Finality.CONFIRMED,
    )
    assert t1["prior_finality"] == Finality.OBSERVED.value
    assert t1["finality"] == Finality.CONFIRMED.value

    t2 = store.apply_finality_transition(
        record_id=block.record_id,
        target=Finality.FINALIZED,
    )
    assert t2["prior_finality"] == Finality.CONFIRMED.value
    transitions = store.list_finality_transitions(record_id=block.record_id)
    assert len(transitions) == 2

    with pytest.raises(InvalidRequestError, match="illegal finality"):
        store.apply_finality_transition(
            record_id=block.record_id,
            target=Finality.OBSERVED,  # cannot downgrade
        )


# ---------------------------------------------------------------------------
# CID / encrypted object refs (no raw bytes)
# ---------------------------------------------------------------------------


def test_encrypted_object_ref_stores_cid_digest_only(
    store: DuckDBWalletStore,
    chain: ChainRef,
    provenance: Provenance,
    context: OperationContext,
) -> None:
    block = _block(chain, provenance, sequence=1, block_hash="0x01")
    _run(store.write(RecordBatch(records=(block,)), context=context))
    _run(store.commit(None, context=context))

    # Projection from ledger write already created a ref from provenance.
    refs = store.list_records("encrypted_object_refs")
    assert len(refs) >= 1
    ref = refs[0]
    assert ref["digest"] == DIGEST
    assert ref["cid"] == "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
    assert "body" not in ref
    assert "raw_payload" not in ref
    assert "payload_bytes" not in ref

    manual = store.put_encrypted_object_ref(
        RawPayloadRef(
            digest="sha256:" + ("ef" * 32),
            cid="bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzda",
            media_type="application/octet-stream",
            byte_length=64,
        ),
        chain=chain,
        provenance=provenance,
        finality=Finality.OBSERVED,
        related_record_id=block.record_id,
    )
    assert manual["cid"] == "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzda"
    loaded = store.get_encrypted_object_ref(manual["ref_id"])
    assert loaded is not None
    assert loaded["digest"].startswith("sha256:")


def test_transfer_monetary_amount_remains_string(
    store: DuckDBWalletStore,
    chain: ChainRef,
    provenance: Provenance,
    context: OperationContext,
) -> None:
    transfer = _transfer(chain, provenance, tx_hash="0xtx1", sequence=42)
    _run(store.write(RecordBatch(records=(transfer,)), context=context))
    _run(store.commit(None, context=context))
    row = store.get_record(transfer.record_id)
    assert row is not None
    assert row["amount_base_units"] == "1000000000000000000"
    assert type(row["amount_base_units"]) is str


# ---------------------------------------------------------------------------
# Optional DuckDB connection (when installed)
# ---------------------------------------------------------------------------


def test_optional_duckdb_connection_installs_schema_and_persists(
    chain: ChainRef,
    provenance: Provenance,
    identity: CheckpointIdentity,
    context: OperationContext,
) -> None:
    duckdb = pytest.importorskip("duckdb")
    conn = duckdb.connect(":memory:")
    store = open_wallet_store(connection=conn, scope="wallet:duckdb")
    block = _block(chain, provenance, sequence=1, block_hash="0x01")
    _run(store.write(RecordBatch(records=(block,)), context=context))
    _run(store.commit(None, context=context))
    cp = build_checkpoint(identity, sequence=1, block_hash="0x01")
    assert _run(
        store.compare_and_set(
            identity.key,
            expected_revision=None,
            checkpoint=cp,
            context=context,
        )
    )
    # Rows visible via DuckDB SQL.
    count = conn.execute("SELECT COUNT(*) FROM blocks").fetchone()[0]
    assert count == 1
    heads = conn.execute("SELECT COUNT(*) FROM _wallet_checkpoint_heads").fetchone()[0]
    assert heads == 1
    conn.close()


def test_factory_open_wallet_store() -> None:
    store = open_wallet_store(scope="s")
    assert isinstance(store, DuckDBWalletStore)
    assert store.scope == "s"
