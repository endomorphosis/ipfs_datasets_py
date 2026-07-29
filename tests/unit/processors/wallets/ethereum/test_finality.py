from __future__ import annotations

from collections.abc import Mapping

from ipfs_datasets_py.processors.wallets.checkpoints import (
    CheckpointIdentity,
    HashAnchor,
    build_checkpoint,
)
from ipfs_datasets_py.processors.wallets.ethereum import (
    ETHEREUM_MAINNET,
    EthereumFinalityPolicy,
    EvmHead,
)
from ipfs_datasets_py.processors.wallets.finality import ReorgKind
from ipfs_datasets_py.processors.wallets.models import Finality, LedgerPosition
from ipfs_datasets_py.processors.wallets.protocols import OperationContext


class _Record:
    def __init__(self, sequence: int, state: Finality = Finality.OBSERVED) -> None:
        self.ledger_position = LedgerPosition(sequence=sequence, hash="0x" + "10" * 32)
        self.finality = state
        self.record_id = (
            "urn:wallet:transaction:sha256:" + "aa" * 32
        )


def test_explicit_safe_and_finalized_tags_override_depth_fallback(
    rpc_session: Mapping[str, object],
) -> None:
    head = EvmHead(
        latest=rpc_session["latest"],  # type: ignore[arg-type]
        safe=rpc_session["safe"],  # type: ignore[arg-type]
        finalized=rpc_session["finalized"],  # type: ignore[arg-type]
        explicit_tags_supported=True,
    )
    policy = EthereumFinalityPolicy(
        safe_fallback_depth=100,
        finalized_fallback_depth=200,
    )
    finalized = policy.classify(
        _Record(16), head=head, context=OperationContext("finality")
    )
    safe = policy.classify(
        _Record(31), head=head, context=OperationContext("finality")
    )
    observed = policy.classify(
        _Record(32), head=head, context=OperationContext("finality")
    )
    assert finalized.state is Finality.FINALIZED
    assert finalized.source == "finalized_tag"
    assert safe.state is Finality.SAFE
    assert safe.source == "safe_tag"
    assert observed.state is Finality.OBSERVED


def test_confirmation_fallback_is_explicitly_labeled(
    rpc_session: Mapping[str, object],
) -> None:
    head = EvmHead(
        latest=rpc_session["latest"],  # type: ignore[arg-type]
        safe=None,
        finalized=None,
        explicit_tags_supported=False,
    )
    policy = EthereumFinalityPolicy(
        confirmed_depth=1,
        safe_fallback_depth=12,
        finalized_fallback_depth=16,
    )
    result = policy.classify(
        _Record(16), head=head, context=OperationContext("finality")
    )
    assert result.state is Finality.FINALIZED
    assert result.confirmations == 16
    assert result.source == "confirmation_fallback"
    assert result.explicit_tags_supported is False


def test_shallow_reorg_emits_corrections_and_rewinds(
    reorg_fixture: Mapping[str, object],
) -> None:
    fixture_checkpoint = reorg_fixture["checkpoint"]  # type: ignore[index]
    replacement = reorg_fixture["replacement"]  # type: ignore[index]
    history = tuple(
        HashAnchor(item["sequence"], item["block_hash"])  # type: ignore[index]
        for item in fixture_checkpoint["history"]  # type: ignore[index]
    )
    identity = CheckpointIdentity(
        chain=ETHEREUM_MAINNET.to_chain_ref(),
        provider="fixture-rpc",
        scope="ledger",
        normalized_schema_major=1,
        normalizer_version="ethereum-normalizer-v1",
    )
    checkpoint = build_checkpoint(
        identity,
        sequence=fixture_checkpoint["sequence"],  # type: ignore[index]
        block_hash=fixture_checkpoint["block_hash"],  # type: ignore[index]
        prior_history=history[:-1],
        safety_depth=8,
    )
    remote_history = tuple(
        HashAnchor(item["sequence"], item["block_hash"])  # type: ignore[index]
        for item in replacement["remote_history"]  # type: ignore[index]
    )
    observed_data = replacement["observed"]  # type: ignore[index]
    observed = HashAnchor(
        observed_data["sequence"], observed_data["block_hash"]  # type: ignore[index]
    )
    record_id = replacement["orphaned_record_ids"][0]  # type: ignore[index]
    policy = EthereumFinalityPolicy(max_reorg_depth=8)
    decision = policy.evaluate_reorg(
        checkpoint,
        observed_anchor=observed,
        context=OperationContext("reorg"),
        remote_history=remote_history,
        record_ids_by_hash={
            fixture_checkpoint["block_hash"]: [record_id]  # type: ignore[index]
        },
        prior_finality_by_id={record_id: Finality.CONFIRMED},
    )
    assert decision.kind is ReorgKind.SHALLOW
    assert decision.rewind_sequence == replacement["expected_rewind_sequence"]  # type: ignore[index]
    assert len(decision.corrections) == 1
    assert decision.corrections[0].record_id == record_id
    assert decision.corrections[0].new_finality is Finality.ORPHANED

    rewound = policy.apply_shallow_rewind(checkpoint, decision)
    assert rewound.anchor.sequence == 15
    assert rewound.continuation_token is None
    assert rewound.metadata["reorg_kind"] == "shallow"
