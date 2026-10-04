"""Unit tests for agentic multi-agent consensus mechanisms."""

from ipfs_datasets_py.optimizers.agentic.consensus_mechanisms import (
    AgentVote,
    ConsensusManager,
    ConsensusStrategy,
    ThresholdConsensus,
)


def _votes_for_entity(entity_text: str, positive_count: int, total_agents: int):
    votes = []
    for i in range(total_agents):
        entities = []
        if i < positive_count:
            entities.append({"text": entity_text, "type": "Concept", "confidence": 0.9})
        votes.append(AgentVote(agent_id=f"agent_{i}", entities=entities, relationships=[]))
    return votes


def test_threshold_strategy_respects_custom_fraction() -> None:
    manager = ConsensusManager(strategy=ConsensusStrategy.THRESHOLD, threshold_fraction=0.75)
    votes = _votes_for_entity("IPFS", positive_count=2, total_agents=3)  # 2/3 = 0.666...

    result = manager.reach_consensus(votes)

    assert result.consensus_entities == []


def test_threshold_strategy_accepts_when_fraction_met() -> None:
    manager = ConsensusManager(strategy=ConsensusStrategy.THRESHOLD, threshold_fraction=0.66)
    votes = _votes_for_entity("IPFS", positive_count=2, total_agents=3)

    result = manager.reach_consensus(votes)

    assert len(result.consensus_entities) == 1
    assert result.consensus_entities[0]["text"] == "IPFS"


def test_qualified_majority_requires_two_thirds() -> None:
    manager = ConsensusManager(strategy=ConsensusStrategy.QUALIFIED_MAJORITY)

    fail_votes = _votes_for_entity("Filecoin", positive_count=1, total_agents=3)
    fail_result = manager.reach_consensus(fail_votes)
    assert fail_result.consensus_entities == []

    pass_votes = _votes_for_entity("Filecoin", positive_count=2, total_agents=3)
    pass_result = manager.reach_consensus(pass_votes)
    assert len(pass_result.consensus_entities) == 1


def test_threshold_consensus_validates_fraction_range() -> None:
    try:
        ThresholdConsensus(threshold_fraction=0.0)
        raise AssertionError("Expected ValueError for zero threshold")
    except ValueError:
        pass

    try:
        ThresholdConsensus(threshold_fraction=1.1)
        raise AssertionError("Expected ValueError for >1 threshold")
    except ValueError:
        pass
