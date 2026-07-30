"""Unit tests for finality state transitions and reorganization contracts."""

from __future__ import annotations

import asyncio

import pytest

from ipfs_datasets_py.processors.wallets.checkpoints import (
    CheckpointIdentity,
    HashAnchor,
    InMemoryCheckpointStore,
    build_checkpoint,
)
from ipfs_datasets_py.processors.wallets.errors import InvalidRequestError
from ipfs_datasets_py.processors.wallets.finality import (
    CanonicalHistory,
    DepthFinalityPolicy,
    DepthThresholds,
    OrphanCorrection,
    ProvisionalExportNotAllowed,
    ReorgKind,
    ReorgReviewRequired,
    assert_export_finality,
    can_transition,
    common_ancestor,
    is_provisional,
    orphaned_suffix,
    project_orphan_corrections,
    transition,
)
from ipfs_datasets_py.processors.wallets.models import (
    Finality,
    LedgerPosition,
)
from ipfs_datasets_py.processors.wallets.protocols import (
    Capability,
    FinalityPolicy,
    OperationContext,
    RequestLimits,
)


@pytest.fixture
def identity() -> CheckpointIdentity:
    from ipfs_datasets_py.processors.wallets.models import ChainRef

    chain = ChainRef(
        namespace="eip155",
        network="ethereum-mainnet",
        chain_id="1",
        genesis_hash="0xd4e56740f876aef8c010b86a40d5f56745a118d0906a34e69aec8c0db1cb8fa3",
    )
    return CheckpointIdentity(
        chain=chain,
        provider="fixture-rpc",
        scope="wallet:0xabc/transfers",
        normalized_schema_major=1,
        normalizer_version="ethereum-normalizer@1.0.0",
    )


@pytest.fixture
def context() -> OperationContext:
    return OperationContext(request_id="reorg-test-1", limits=RequestLimits())


@pytest.fixture
def policy() -> DepthFinalityPolicy:
    return DepthFinalityPolicy(
        chain_namespaces=frozenset({"eip155:1"}),
        thresholds=DepthThresholds(confirmed=1, safe=4, finalized=12),
        max_reorg_depth=3,
    )


def _run(coro):
    return asyncio.run(coro)


def test_finality_is_enum_not_boolean() -> None:
    assert isinstance(Finality.FINALIZED, Finality)
    assert Finality.FINALIZED.value == "finalized"
    assert Finality.ORPHANED != Finality.FINALIZED
    # Distinct states for provisional and terminal outcomes.
    states = {
        Finality.UNKNOWN,
        Finality.OBSERVED,
        Finality.PENDING,
        Finality.CONFIRMED,
        Finality.SAFE,
        Finality.FINALIZED,
        Finality.ORPHANED,
        Finality.REVERTED,
        Finality.FAILED,
    }
    assert len(states) == 9
    assert is_provisional(Finality.OBSERVED)
    assert is_provisional(Finality.SAFE)
    assert not is_provisional(Finality.FINALIZED)
    assert not is_provisional(Finality.ORPHANED)


def test_finality_state_transitions() -> None:
    assert can_transition(Finality.OBSERVED, Finality.CONFIRMED)
    assert can_transition(Finality.CONFIRMED, Finality.SAFE)
    assert can_transition(Finality.SAFE, Finality.FINALIZED)
    assert can_transition(Finality.OBSERVED, Finality.ORPHANED)
    assert transition(Finality.PENDING, Finality.SAFE) is Finality.SAFE
    with pytest.raises(InvalidRequestError, match="illegal finality transition"):
        transition(Finality.FAILED, Finality.FINALIZED)
    with pytest.raises(InvalidRequestError, match="illegal finality transition"):
        transition(Finality.FINALIZED, Finality.OBSERVED)


def test_depth_finality_policy_implements_protocol(
    policy: DepthFinalityPolicy,
) -> None:
    assert isinstance(policy, FinalityPolicy)
    caps = policy.capabilities
    assert caps.supports(Capability.FINALITY)
    assert caps.supports(Capability.REORG_RECOVERY)


def test_classify_by_confirmation_depth(
    policy: DepthFinalityPolicy,
    context: OperationContext,
) -> None:
    head = {"sequence": 100, "hash": "0xhead"}
    observed = policy.classify(
        {"ledger_position": {"sequence": 100, "hash": "0xa"}, "finality": "unknown"},
        head=head,
        context=context,
    )
    assert observed.state is Finality.OBSERVED
    assert observed.confirmations == 0

    confirmed = policy.classify(
        {"ledger_position": {"sequence": 99, "hash": "0xb"}},
        head=head,
        context=context,
    )
    assert confirmed.state is Finality.CONFIRMED

    safe = policy.classify(
        {"ledger_position": {"sequence": 96, "hash": "0xc"}},
        head=head,
        context=context,
    )
    assert safe.state is Finality.SAFE

    finalized = policy.classify(
        {"ledger_position": {"sequence": 80, "hash": "0xd"}},
        head=head,
        context=context,
    )
    assert finalized.state is Finality.FINALIZED

    pending = policy.classify(
        {"ledger_position": {"sequence": 101, "hash": "0xe"}},
        head=head,
        context=context,
    )
    assert pending.state is Finality.PENDING


def test_common_ancestor_finds_highest_shared_hash() -> None:
    local = CanonicalHistory.from_pairs(
        [(1, "0x01"), (2, "0x02"), (3, "0x03a"), (4, "0x04a")]
    )
    remote = CanonicalHistory.from_pairs(
        [(1, "0x01"), (2, "0x02"), (3, "0x03b"), (4, "0x04b")]
    )
    ancestor = common_ancestor(local, remote)
    assert ancestor is not None
    assert ancestor.sequence == 2
    assert ancestor.block_hash == "0x02"
    assert common_ancestor(local, CanonicalHistory.from_pairs([(9, "0xzz")])) is None


def test_shallow_reorg_finds_ancestor_and_emits_orphan_corrections(
    identity: CheckpointIdentity,
    policy: DepthFinalityPolicy,
    context: OperationContext,
) -> None:
    history = (
        HashAnchor(10, "0x0a"),
        HashAnchor(11, "0x0b"),
        HashAnchor(12, "0x0c-old"),
        HashAnchor(13, "0x0d-old"),
    )
    checkpoint = build_checkpoint(
        identity,
        sequence=13,
        block_hash="0x0d-old",
        safety_depth=3,
        prior_history=history[:-1],
        continuation_token="stale-token",
    )
    remote = CanonicalHistory.from_pairs(
        [
            (10, "0x0a"),
            (11, "0x0b"),
            (12, "0x0c-new"),
            (13, "0x0d-new"),
            (14, "0x0e-new"),
        ]
    )
    decision = policy.evaluate_reorg(
        checkpoint,
        observed_anchor=HashAnchor(14, "0x0e-new"),
        context=context,
        remote_history=remote,
        record_ids_by_hash={
            "0x0c-old": ("urn:tx:c",),
            "0x0d-old": ("urn:tx:d", "urn:tx:d2"),
        },
        prior_finality_by_id={
            "urn:tx:c": Finality.CONFIRMED,
            "urn:tx:d": Finality.SAFE,
            "urn:tx:d2": Finality.OBSERVED,
        },
    )
    assert decision.kind is ReorgKind.SHALLOW
    assert decision.review_required is False
    assert decision.common_ancestor is not None
    assert decision.common_ancestor.sequence == 11
    assert decision.common_ancestor.block_hash == "0x0b"
    assert decision.rewind_sequence == 11
    assert {a.block_hash for a in decision.orphaned_anchors} == {
        "0x0c-old",
        "0x0d-old",
    }
    assert len(decision.corrections) == 3
    assert all(c.tombstone for c in decision.corrections)
    assert all(c.new_finality is Finality.ORPHANED for c in decision.corrections)
    assert {c.record_id for c in decision.corrections} == {
        "urn:tx:c",
        "urn:tx:d",
        "urn:tx:d2",
    }

    rewound = policy.apply_shallow_rewind(checkpoint, decision)
    assert rewound.anchor.sequence == 11
    assert rewound.anchor.block_hash == "0x0b"
    # Provider continuation tokens never replace hash anchors after rewind.
    assert rewound.continuation_token is None
    assert rewound.history[-1].matches(HashAnchor(11, "0x0b"))
    assert decision.rewind_sequence == 11


def test_shallow_reorg_rewind_with_remote_via_evaluate(
    identity: CheckpointIdentity,
    policy: DepthFinalityPolicy,
    context: OperationContext,
) -> None:
    history = tuple(HashAnchor(i, f"0x{i:02x}") for i in range(1, 5))
    checkpoint = build_checkpoint(
        identity,
        sequence=4,
        block_hash="0x04",
        prior_history=history[:-1],
    )
    # Divergent tip at same height is still a shallow reorg when ancestor exists.
    remote = CanonicalHistory.from_pairs(
        [(1, "0x01"), (2, "0x02"), (3, "0x03-new"), (4, "0x04-new")]
    )
    decision = policy.evaluate_reorg(
        checkpoint,
        observed_anchor=HashAnchor(4, "0x04-new"),
        context=context,
        remote_history=remote,
        record_ids_by_hash={"0x03": ("r3",), "0x04": ("r4",)},
        prior_finality_by_id={"r3": Finality.CONFIRMED, "r4": Finality.CONFIRMED},
    )
    assert decision.kind is ReorgKind.SHALLOW
    assert decision.common_ancestor is not None
    assert decision.common_ancestor.sequence == 2
    rewound = policy.apply_shallow_rewind(checkpoint, decision)
    assert rewound.anchor.sequence == 2


def test_deep_reorg_stops_for_review(
    identity: CheckpointIdentity,
    policy: DepthFinalityPolicy,
    context: OperationContext,
) -> None:
    # max_reorg_depth=3; orphan four blocks after ancestor.
    history = tuple(HashAnchor(i, f"0xold{i}") for i in range(1, 8))
    checkpoint = build_checkpoint(
        identity,
        sequence=7,
        block_hash="0xold7",
        safety_depth=3,
        prior_history=history[:-1],
    )
    remote = CanonicalHistory.from_pairs(
        [(1, "0xold1"), (2, "0xold2")]
        + [(i, f"0xnew{i}") for i in range(3, 10)]
    )
    decision = policy.evaluate_reorg(
        checkpoint,
        observed_anchor=HashAnchor(9, "0xnew9"),
        context=context,
        remote_history=remote,
    )
    assert decision.kind is ReorgKind.DEEP
    assert decision.review_required is True
    assert decision.common_ancestor is not None
    assert decision.common_ancestor.sequence == 2
    assert decision.corrections == ()

    with pytest.raises(ReorgReviewRequired, match="deep reorg|safety window"):
        policy.rewind_position(
            checkpoint,
            observed_anchor=HashAnchor(9, "0xnew9"),
            context=context,
        )

    with pytest.raises(ReorgReviewRequired):
        # apply_shallow_rewind must refuse deep decisions.
        policy.apply_shallow_rewind(checkpoint, decision)


def test_deep_reorg_no_common_ancestor(
    identity: CheckpointIdentity,
    policy: DepthFinalityPolicy,
    context: OperationContext,
) -> None:
    history = tuple(HashAnchor(i, f"0x{i:02x}") for i in range(10, 15))
    checkpoint = build_checkpoint(
        identity,
        sequence=14,
        block_hash="0x0e",
        prior_history=history[:-1],
    )
    remote = CanonicalHistory.from_pairs([(100, "0xaa"), (101, "0xbb")])
    decision = policy.evaluate_reorg(
        checkpoint,
        observed_anchor=HashAnchor(101, "0xbb"),
        context=context,
        remote_history=remote,
    )
    assert decision.kind is ReorgKind.DEEP
    assert decision.common_ancestor is None
    assert decision.review_required is True


def test_matching_anchor_is_not_a_reorg(
    identity: CheckpointIdentity,
    policy: DepthFinalityPolicy,
    context: OperationContext,
) -> None:
    checkpoint = build_checkpoint(identity, sequence=5, block_hash="0x05")
    decision = policy.evaluate_reorg(
        checkpoint,
        observed_anchor=HashAnchor(5, "0x05"),
        context=context,
    )
    assert decision.kind is ReorgKind.NONE
    assert policy.rewind_position(
        checkpoint,
        observed_anchor=HashAnchor(5, "0x05"),
        context=context,
    ) is None


def test_orphan_suffix_and_project_corrections() -> None:
    history = (
        HashAnchor(1, "0x01"),
        HashAnchor(2, "0x02"),
        HashAnchor(3, "0x03"),
    )
    ancestor = HashAnchor(1, "0x01")
    orphans = orphaned_suffix(history, ancestor)
    assert [a.sequence for a in orphans] == [2, 3]
    corrections = project_orphan_corrections(
        orphaned_anchors=orphans,
        record_ids_by_hash={"0x02": ("a",), "0x03": ("b",)},
        prior_finality_by_id={"a": Finality.OBSERVED, "b": Finality.CONFIRMED},
        ancestor=ancestor,
        target=Finality.REVERTED,
    )
    assert len(corrections) == 2
    assert all(isinstance(c, OrphanCorrection) for c in corrections)
    assert all(c.new_finality is Finality.REVERTED for c in corrections)


def test_provisional_export_requires_explicit_opt_in() -> None:
    with pytest.raises(ProvisionalExportNotAllowed, match="allow_provisional"):
        assert_export_finality([Finality.OBSERVED, Finality.FINALIZED])
    with pytest.raises(ProvisionalExportNotAllowed):
        assert_export_finality({Finality.SAFE: 3, Finality.FINALIZED: 10})
    # Explicit opt-in permits provisional states.
    assert_export_finality(
        [Finality.OBSERVED, Finality.FINALIZED],
        allow_provisional=True,
    )
    # Finalized-only export is allowed without opt-in.
    assert_export_finality([Finality.FINALIZED])
    assert_export_finality({Finality.FINALIZED: 5, Finality.ORPHANED: 1})


def test_checkpoint_cas_after_shallow_rewind(
    identity: CheckpointIdentity,
    policy: DepthFinalityPolicy,
    context: OperationContext,
) -> None:
    store = InMemoryCheckpointStore()
    history = (
        HashAnchor(1, "0x01"),
        HashAnchor(2, "0x02"),
        HashAnchor(3, "0x03-old"),
    )
    original = build_checkpoint(
        identity,
        sequence=3,
        block_hash="0x03-old",
        prior_history=history[:-1],
    )
    assert _run(
        store.compare_and_set(
            identity.key,
            expected_revision=None,
            checkpoint=original,
            context=context,
        )
    )
    remote = CanonicalHistory.from_pairs(
        [(1, "0x01"), (2, "0x02"), (3, "0x03-new")]
    )
    decision = policy.evaluate_reorg(
        original,
        observed_anchor=HashAnchor(3, "0x03-new"),
        context=context,
        remote_history=remote,
        record_ids_by_hash={"0x03-old": ("tx-old",)},
        prior_finality_by_id={"tx-old": Finality.CONFIRMED},
    )
    assert decision.kind is ReorgKind.SHALLOW
    rewound = policy.apply_shallow_rewind(original, decision)
    assert _run(
        store.replace_after_rewind(
            identity,
            expected_revision=original.revision,
            rewound=rewound,
            context=context,
        )
    )
    stored = _run(store.load(identity.key, context=context))
    assert stored is not None
    assert stored.anchor.sequence == 2
    assert stored.continuation_token is None


def test_rewind_rejects_token_only_observed_anchor(
    identity: CheckpointIdentity,
    policy: DepthFinalityPolicy,
    context: OperationContext,
) -> None:
    checkpoint = build_checkpoint(identity, sequence=1, block_hash="0x01")
    with pytest.raises(Exception, match="hash"):
        policy.rewind_position(
            checkpoint,
            observed_anchor=LedgerPosition(sequence=2, hash=None),
            context=context,
        )


def test_classify_preserves_orphan_state(
    policy: DepthFinalityPolicy,
    context: OperationContext,
) -> None:
    result = policy.classify(
        {
            "ledger_position": {"sequence": 50, "hash": "0xorph"},
            "finality": Finality.ORPHANED,
        },
        head={"sequence": 100, "hash": "0xhead"},
        context=context,
    )
    assert result.state is Finality.ORPHANED
