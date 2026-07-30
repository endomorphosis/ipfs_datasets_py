"""Unit tests for hash-anchored compare-and-set wallet checkpoints."""

from __future__ import annotations

import asyncio
import json

import pytest

from ipfs_datasets_py.processors.wallets.checkpoints import (
    CheckpointCommitCoordinator,
    CheckpointIdentity,
    CheckpointRecord,
    HashAnchor,
    InMemoryCheckpointStore,
    SinkCommitReceipt,
    assert_hash_anchor_present,
    build_checkpoint,
    checkpoint_content_fingerprint,
    new_revision,
    validate_resume,
)
from ipfs_datasets_py.processors.wallets.errors import CheckpointError, InvalidRequestError
from ipfs_datasets_py.processors.wallets.models import ChainRef, LedgerPosition
from ipfs_datasets_py.processors.wallets.protocols import (
    CheckpointStore,
    OperationContext,
    RequestLimits,
)


@pytest.fixture
def chain() -> ChainRef:
    return ChainRef(
        namespace="eip155",
        network="ethereum-mainnet",
        chain_id="1",
        genesis_hash="0xd4e56740f876aef8c010b86a40d5f56745a118d0906a34e69aec8c0db1cb8fa3",
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
    return OperationContext(request_id="ckpt-test-1", limits=RequestLimits())


def _run(coro):
    return asyncio.run(coro)


def test_identity_binds_chain_network_genesis_provider_scope_schema_normalizer(
    chain: ChainRef,
) -> None:
    a = CheckpointIdentity(
        chain=chain,
        provider="rpc-a",
        scope="wallet:1",
        normalized_schema_major=1,
        normalizer_version="n@1",
    )
    b = CheckpointIdentity(
        chain=chain,
        provider="rpc-a",
        scope="wallet:1",
        normalized_schema_major=1,
        normalizer_version="n@1",
    )
    c = CheckpointIdentity(
        chain=chain,
        provider="rpc-b",
        scope="wallet:1",
        normalized_schema_major=1,
        normalizer_version="n@1",
    )
    d = CheckpointIdentity(
        chain=ChainRef(
            namespace=chain.namespace,
            network="sepolia",
            chain_id="11155111",
            genesis_hash="0xothergenesis",
        ),
        provider="rpc-a",
        scope="wallet:1",
        normalized_schema_major=1,
        normalizer_version="n@1",
    )
    e = CheckpointIdentity(
        chain=chain,
        provider="rpc-a",
        scope="wallet:1",
        normalized_schema_major=2,
        normalizer_version="n@1",
    )
    f = CheckpointIdentity(
        chain=chain,
        provider="rpc-a",
        scope="wallet:1",
        normalized_schema_major=1,
        normalizer_version="n@2",
    )
    assert a.compatible_with(b)
    assert a.key == b.key
    assert a.key != c.key
    assert a.key != d.key
    assert a.key != e.key
    assert a.key != f.key
    assert "genesis_hash" in a.to_dict()["chain"]
    assert a.to_dict()["normalized_schema_major"] == 1
    assert a.to_dict()["normalizer_version"] == "n@1"


def test_hash_anchor_required_continuation_token_never_replaces_anchor() -> None:
    with pytest.raises(CheckpointError, match="continuation tokens never replace"):
        assert_hash_anchor_present(
            LedgerPosition(sequence=10, hash=None),
            continuation_token="page-token-xyz",
        )
    with pytest.raises(CheckpointError, match="hash anchor"):
        assert_hash_anchor_present(LedgerPosition(sequence=10, hash=None))
    anchor = assert_hash_anchor_present(
        LedgerPosition(sequence=10, hash="0xabc"),
        continuation_token="page-token-xyz",
    )
    assert anchor.block_hash == "0xabc"
    assert anchor.sequence == 10


def test_build_checkpoint_includes_history_and_cursor(
    identity: CheckpointIdentity,
) -> None:
    prior = (
        HashAnchor(1, "0x01"),
        HashAnchor(2, "0x02"),
    )
    cp = build_checkpoint(
        identity,
        sequence=3,
        block_hash="0x03",
        safety_depth=12,
        continuation_token="cursor-3",
        prior_history=prior,
        sink_commit_id="commit-1",
    )
    assert isinstance(cp, CheckpointRecord)
    assert cp.anchor.sequence == 3
    assert cp.history[-1].block_hash == "0x03"
    assert len(cp.history) == 3
    cursor = cp.to_cursor()
    assert cursor.provider == identity.provider
    assert cursor.scope == identity.scope
    assert cursor.position.hash == "0x03"
    assert cursor.continuation_token == "cursor-3"
    assert cursor.normalized_schema_major == 1
    assert cursor.normalizer_version == identity.normalizer_version
    assert cursor.chain.genesis_hash == identity.chain.genesis_hash


def test_inmemory_store_implements_checkpoint_store_protocol(
    identity: CheckpointIdentity,
    context: OperationContext,
) -> None:
    store = InMemoryCheckpointStore()
    assert isinstance(store, CheckpointStore)
    loaded = _run(store.load(identity.key, context=context))
    assert loaded is None
    cp = build_checkpoint(identity, sequence=5, block_hash="0x05")
    ok = _run(
        store.compare_and_set(
            identity.key,
            expected_revision=None,
            checkpoint=cp,
            context=context,
        )
    )
    assert ok is True
    again = _run(store.load(identity.key, context=context))
    assert again is not None
    assert again.revision == cp.revision
    assert again.anchor.block_hash == "0x05"


def test_compare_and_set_conflict_and_success(
    identity: CheckpointIdentity,
    context: OperationContext,
) -> None:
    store = InMemoryCheckpointStore()
    first = build_checkpoint(identity, sequence=1, block_hash="0x01")
    assert _run(
        store.compare_and_set(
            identity.key,
            expected_revision=None,
            checkpoint=first,
            context=context,
        )
    )
    stale = build_checkpoint(identity, sequence=2, block_hash="0x02")
    assert not _run(
        store.compare_and_set(
            identity.key,
            expected_revision=None,
            checkpoint=stale,
            context=context,
        )
    )
    next_cp = build_checkpoint(
        identity,
        sequence=2,
        block_hash="0x02",
        prior_history=first.history,
    )
    assert _run(
        store.compare_and_set(
            identity.key,
            expected_revision=first.revision,
            checkpoint=next_cp,
            context=context,
        )
    )
    stored = _run(store.load(identity.key, context=context))
    assert stored is not None
    assert stored.anchor.sequence == 2
    assert store.cas_attempts == 3
    assert store.cas_successes == 2


def test_cas_rejects_identity_mismatch_on_scope_key(
    identity: CheckpointIdentity,
    context: OperationContext,
) -> None:
    store = InMemoryCheckpointStore()
    cp = build_checkpoint(identity, sequence=1, block_hash="0x01")
    with pytest.raises(CheckpointError, match="does not bind"):
        _run(
            store.compare_and_set(
                "unrelated-scope-key",
                expected_revision=None,
                checkpoint=cp,
                context=context,
            )
        )


def test_sink_commit_must_precede_checkpoint_cas(
    identity: CheckpointIdentity,
    context: OperationContext,
) -> None:
    store = InMemoryCheckpointStore()
    coordinator = CheckpointCommitCoordinator(store)
    cp = build_checkpoint(
        identity,
        sequence=9,
        block_hash="0x09",
        sink_commit_id="commit-abc",
    )
    with pytest.raises(CheckpointError, match="sink commit must precede"):
        _run(
            coordinator.compare_and_set_after_commit(
                identity,
                expected_revision=None,
                checkpoint=cp,
                context=context,
            )
        )
    coordinator.note_sink_commit(
        SinkCommitReceipt(
            commit_id="commit-abc",
            scope_key=identity.key,
            record_count=3,
            content_digest="sha256:deadbeef",
        )
    )
    assert _run(
        coordinator.compare_and_set_after_commit(
            identity,
            expected_revision=None,
            checkpoint=cp,
            context=context,
        )
    )
    # Pending receipt is cleared after successful CAS.
    assert coordinator.pending_commit(identity.key) is None
    stored = _run(store.load(identity.key, context=context))
    assert stored is not None
    assert stored.sink_commit_id == "commit-abc"


def test_sink_commit_id_mismatch_fails_closed(
    identity: CheckpointIdentity,
    context: OperationContext,
) -> None:
    store = InMemoryCheckpointStore()
    coordinator = CheckpointCommitCoordinator(store)
    coordinator.note_sink_commit(
        SinkCommitReceipt(
            commit_id="commit-expected",
            scope_key=identity.key,
            record_count=1,
        )
    )
    cp = build_checkpoint(
        identity,
        sequence=1,
        block_hash="0x01",
        sink_commit_id="commit-other",
    )
    with pytest.raises(CheckpointError, match="sink_commit_id"):
        _run(
            coordinator.compare_and_set_after_commit(
                identity,
                expected_revision=None,
                checkpoint=cp,
                context=context,
            )
        )


def test_crash_replay_is_idempotent(
    identity: CheckpointIdentity,
    context: OperationContext,
) -> None:
    """Simulated crash after sink commit: replaying CAS is safe and stable."""

    store = InMemoryCheckpointStore()
    coordinator = CheckpointCommitCoordinator(store)

    # First successful write.
    receipt = SinkCommitReceipt(
        commit_id="commit-1",
        scope_key=identity.key,
        record_count=10,
    )
    coordinator.note_sink_commit(receipt)
    cp1 = build_checkpoint(
        identity,
        sequence=100,
        block_hash="0x64",
        sink_commit_id=receipt.commit_id,
        continuation_token="tok-100",
    )
    assert _run(
        coordinator.compare_and_set_after_commit(
            identity,
            expected_revision=None,
            checkpoint=cp1,
            context=context,
        )
    )
    fingerprint = checkpoint_content_fingerprint(cp1)

    # Crash recovery: load stored revision; re-commit sink (same data); CAS with
    # stale expected revision fails; reload and either skip or advance correctly.
    stored = _run(store.load(identity.key, context=context))
    assert stored is not None
    assert checkpoint_content_fingerprint(stored) == fingerprint

    # Idempotent re-attempt with the pre-crash expected revision (None) fails.
    coordinator.note_sink_commit(receipt)
    replay = build_checkpoint(
        identity,
        sequence=100,
        block_hash="0x64",
        sink_commit_id=receipt.commit_id,
        continuation_token="tok-100",
    )
    assert not _run(
        coordinator.compare_and_set_after_commit(
            identity,
            expected_revision=None,
            checkpoint=replay,
            context=context,
        )
    )
    # Using the stored revision with identical durable content also CAS-fails
    # because revision tokens differ, but the loaded durable state is unchanged.
    stored_after = _run(store.load(identity.key, context=context))
    assert stored_after is not None
    assert checkpoint_content_fingerprint(stored_after) == fingerprint
    assert stored_after.revision == cp1.revision

    # A true advance after recovery uses the loaded revision.
    coordinator.note_sink_commit(
        SinkCommitReceipt(
            commit_id="commit-2",
            scope_key=identity.key,
            record_count=2,
        )
    )
    cp2 = build_checkpoint(
        identity,
        sequence=101,
        block_hash="0x65",
        sink_commit_id="commit-2",
        prior_history=stored_after.history,
    )
    assert _run(
        coordinator.compare_and_set_after_commit(
            identity,
            expected_revision=stored_after.revision,
            checkpoint=cp2,
            context=context,
        )
    )
    final = _run(store.load(identity.key, context=context))
    assert final is not None
    assert final.anchor.sequence == 101


def test_validate_resume_identity_and_matching_anchor(
    identity: CheckpointIdentity,
) -> None:
    cp = build_checkpoint(identity, sequence=7, block_hash="0x07")
    validate_resume(cp, observed_anchor=HashAnchor(7, "0x07"), identity=identity)
    other = CheckpointIdentity(
        chain=identity.chain,
        provider="other",
        scope=identity.scope,
        normalized_schema_major=1,
        normalizer_version=identity.normalizer_version,
    )
    with pytest.raises(CheckpointError, match="identity"):
        validate_resume(cp, observed_anchor=HashAnchor(7, "0x07"), identity=other)
    # Divergence is allowed; reorg path handles it.
    validate_resume(cp, observed_anchor=HashAnchor(8, "0x08"), identity=identity)


def test_load_by_raw_scope_string(
    identity: CheckpointIdentity,
    context: OperationContext,
) -> None:
    store = InMemoryCheckpointStore()
    cp = build_checkpoint(identity, sequence=1, block_hash="0x01")
    assert _run(
        store.compare_and_set(
            identity.key,
            expected_revision=None,
            checkpoint=cp,
            context=context,
        )
    )
    by_scope = _run(store.load(identity.scope, context=context))
    assert by_scope is not None
    assert by_scope.checkpoint_id == cp.checkpoint_id


def test_history_is_bounded(
    identity: CheckpointIdentity,
    context: OperationContext,
) -> None:
    store = InMemoryCheckpointStore(history_limit=3)
    revision: str | None = None
    history: tuple[HashAnchor, ...] = ()
    for seq in range(1, 6):
        cp = build_checkpoint(
            identity,
            sequence=seq,
            block_hash=f"0x{seq:02x}",
            prior_history=history,
        )
        assert _run(
            store.compare_and_set(
                identity.key,
                expected_revision=revision,
                checkpoint=cp,
                context=context,
            )
        )
        stored = _run(store.load(identity.key, context=context))
        assert stored is not None
        revision = stored.revision
        history = stored.history
    assert len(history) == 3
    assert history[0].sequence == 3
    assert history[-1].sequence == 5


def test_new_revision_is_unique() -> None:
    assert new_revision() != new_revision()


def test_identity_rejects_empty_fields(chain: ChainRef) -> None:
    with pytest.raises(InvalidRequestError):
        CheckpointIdentity(
            chain=chain,
            provider="",
            scope="s",
            normalized_schema_major=1,
            normalizer_version="n",
        )
    with pytest.raises(InvalidRequestError):
        CheckpointIdentity(
            chain=chain,
            provider="p",
            scope="s",
            normalized_schema_major=0,
            normalizer_version="n",
        )


def test_checkpoint_to_dict_round_trip_fields(
    identity: CheckpointIdentity,
) -> None:
    cp = build_checkpoint(
        identity,
        sequence=42,
        block_hash="0x2a",
        continuation_token="page-9",
        metadata={"request_id": "r1"},
    )
    payload = cp.to_dict()
    assert payload["schema_version"].startswith("wallet-checkpoint")
    assert payload["anchor"]["block_hash"] == "0x2a"
    assert payload["continuation_token"] == "page-9"
    assert payload["identity"]["provider"] == identity.provider
    assert payload["metadata"]["request_id"] == "r1"


def test_checkpoint_preserves_and_freezes_nested_public_metadata(
    identity: CheckpointIdentity,
) -> None:
    metadata = {
        "batch": {
            "token": {"symbol": "USDC", "token_id": "public-42"},
            "positions": [7, 8, 9],
        }
    }
    checkpoint = build_checkpoint(
        identity,
        sequence=43,
        block_hash="0x2b",
        continuation_token="opaque-provider-token",
        metadata=metadata,
    )
    metadata["batch"]["positions"].append(10)  # type: ignore[index,union-attr]

    payload = checkpoint.to_dict()
    assert payload["metadata"]["batch"]["positions"] == [7, 8, 9]
    assert payload["metadata"]["batch"]["token"]["symbol"] == "USDC"
    assert payload["continuation_token"] == "opaque-provider-token"
    assert json.loads(json.dumps(payload, sort_keys=True)) == payload


@pytest.mark.parametrize(
    ("metadata", "continuation_token"),
    (
        (
            {"outer": [{"private_key": "correct-horse-battery-staple-wallet-secret"}]},
            "page-1",
        ),
        (
            {"outer": {"safe_name": "vault://wallet/provider/main-token"}},
            "page-1",
        ),
        ({}, "correct-horse-battery-staple-wallet-secret"),
    ),
)
def test_checkpoint_rejects_nested_secrets_without_repr_or_error_leaks(
    identity: CheckpointIdentity,
    metadata: dict[str, object],
    continuation_token: str,
) -> None:
    with pytest.raises(ValueError, match="wallet serialization") as caught:
        build_checkpoint(
            identity,
            sequence=44,
            block_hash="0x2c",
            continuation_token=continuation_token,
            metadata=metadata,
        )

    rendered = f"{caught.value!s}\n{caught.value!r}"
    assert "correct-horse-battery-staple-wallet-secret" not in rendered
    assert "vault://wallet/provider/main-token" not in rendered
