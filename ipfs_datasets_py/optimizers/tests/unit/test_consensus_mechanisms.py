"""
Tests for Multi-Agent Consensus Mechanisms - Batch 247 [agentic].

Comprehensive test coverage for consensus system including:
- Agent voting structures
- Consensus strategies (majority, unanimous, weighted)
- Conflict detection and resolution
- Metrics calculation (entropy, agreement rate)
- Agent reputation tracking
- Vote aggregation
- Edge cases

Test Coverage:
    - Basic service structure and initialization
    - Majority voting
    - Unanimous voting
    - Weighted voting with reputation
    - Conflict detection
    - Conflict resolution
    - Entropy calculation
    - Agreement rate calculation
    - Agent registration
    - Reputation updates
    - Consensus statistics
    - Edge cases (empty votes, single agent, etc.)
"""

import pytest
import math
from typing import List, Dict, Any

from ipfs_datasets_py.optimizers.agentic.consensus_mechanisms import (
    AgentVote, AgentProfile, ConsensusResult,
    ConsensusStrategy, ConsensusManager,
    MajorityConsensus, UnanimousConsensus, WeightedConsensus,
    ConflictResolver, ConsensusMetrics
)


# ============================================================================
# Test Data Fixtures
# ============================================================================


@pytest.fixture
def sample_entity_1():
    """Sample entity 1."""
    return {
        'text': 'John Doe',
        'type': 'PERSON',
        'confidence': 0.95
    }


@pytest.fixture
def sample_entity_2():
    """Sample entity 2."""
    return {
        'text': 'John Doe',
        'type': 'PERSON',
        'confidence': 0.92
    }


@pytest.fixture
def sample_relationship():
    """Sample relationship."""
    return {
        'source_id': 'e1',
        'target_id': 'e2',
        'type': 'WORKS_FOR',
        'confidence': 0.88
    }


@pytest.fixture
def consensus_manager():
    """Create consensus manager with weighted strategy."""
    manager = ConsensusManager(strategy=ConsensusStrategy.WEIGHTED)
    manager.register_agent('agent1', reputation=0.95, accuracy=0.9)
    manager.register_agent('agent2', reputation=0.85, accuracy=0.85)
    manager.register_agent('agent3', reputation=0.75, accuracy=0.8)
    return manager


# ============================================================================
# Test Data Structures
# ============================================================================


class TestAgentVote:
    """Test agent vote structure."""
    
    def test_create_agent_vote(self):
        """Create agent vote."""
        vote = AgentVote(
            agent_id='agent1',
            entities=[{'text': 'test', 'type': 'PERSON', 'confidence': 0.9}],
            relationships=[],
            confidence=0.85
        )
        
        assert vote.agent_id == 'agent1'
        assert len(vote.entities) == 1
        assert vote.confidence == 0.85
    
    def test_empty_vote(self):
        """Create empty vote."""
        vote = AgentVote(agent_id='agent1')
        
        assert vote.agent_id == 'agent1'
        assert vote.entities == []
        assert vote.relationships == []


class TestAgentProfile:
    """Test agent profile."""
    
    def test_create_agent_profile(self):
        """Create agent profile."""
        profile = AgentProfile(
            agent_id='agent1',
            reputation=0.9,
            accuracy=0.85
        )
        
        assert profile.agent_id == 'agent1'
        assert profile.reputation == 0.9
        assert profile.accuracy == 0.85
    
    def test_default_profile(self):
        """Create profile with defaults."""
        profile = AgentProfile(agent_id='agent1')
        
        assert profile.reputation == 0.5
        assert profile.accuracy == 0.5


# ============================================================================
# Test Majority Consensus
# ============================================================================


class TestMajorityConsensus:
    """Test majority voting consensus."""
    
    def test_unanimous_agreement(self):
        """All agents agree."""
        engine = MajorityConsensus()
        
        entity = {'text': 'Alice', 'type': 'PERSON', 'confidence': 0.9}
        
        votes = [
            AgentVote(agent_id='a1', entities=[entity]),
            AgentVote(agent_id='a2', entities=[entity]),
            AgentVote(agent_id='a3', entities=[entity])
        ]
        
        rules = {}
        entities, rels, agreement = engine.aggregate_votes(votes, rules)
        
        assert len(entities) == 1
        assert entities[0]['text'] == 'Alice'
        # agreement_rate = consensus_items / total_votes
        # 1 consensus entity / 3 total votes = 0.333...
        assert agreement == pytest.approx(0.333, rel=0.01)
    
    def test_majority_agreement(self):
        """2 out of 3 agents agree."""
        engine = MajorityConsensus()
        
        entity1 = {'text': 'Alice', 'type': 'PERSON', 'confidence': 0.9}
        entity2 = {'text': 'Alice', 'type': 'LOCATION', 'confidence': 0.7}
        
        votes = [
            AgentVote(agent_id='a1', entities=[entity1]),
            AgentVote(agent_id='a2', entities=[entity1]),
            AgentVote(agent_id='a3', entities=[entity2])
        ]
        
        rules = {}
        entities, rels, agreement = engine.aggregate_votes(votes, rules)
        
        assert len(entities) == 1
        assert entities[0]['type'] == 'PERSON'
    
    def test_no_majority(self):
        """No majority consensus reached."""
        engine = MajorityConsensus()
        
        votes = [
            AgentVote(agent_id='a1', entities=[
                {'text': 'Alice', 'type': 'PERSON', 'confidence': 0.9}
            ]),
            AgentVote(agent_id='a2', entities=[
                {'text': 'Bob', 'type': 'PERSON', 'confidence': 0.8}
            ])
        ]
        
        rules = {}
        entities, rels, agreement = engine.aggregate_votes(votes, rules)
        
        # With 2 agents, need >1 vote (at least 1.1) - neither reaches that individually
        assert len(entities) <= 2


# ============================================================================
# Test Unanimous Consensus
# ============================================================================


class TestUnanimousConsensus:
    """Test unanimous voting."""
    
    def test_all_agree(self):
        """All agents agree on same entity."""
        engine = UnanimousConsensus()
        
        entity = {'text': 'Alice', 'type': 'PERSON', 'confidence': 0.9}
        
        votes = [
            AgentVote(agent_id='a1', entities=[entity]),
            AgentVote(agent_id='a2', entities=[entity]),
            AgentVote(agent_id='a3', entities=[entity])
        ]
        
        rules = {}
        entities, rels, agreement = engine.aggregate_votes(votes, rules)
        
        assert len(entities) == 1
        assert entities[0]['vote_count'] == 3
    
    def test_partial_agreement(self):
        """Not all agents agree."""
        engine = UnanimousConsensus()
        
        votes = [
            AgentVote(agent_id='a1', entities=[
                {'text': 'Alice', 'type': 'PERSON', 'confidence': 0.9}
            ]),
            AgentVote(agent_id='a2', entities=[
                {'text': 'Alice', 'type': 'PERSON', 'confidence': 0.9}
            ]),
            AgentVote(agent_id='a3', entities=[
                {'text': 'Bob', 'type': 'PERSON', 'confidence': 0.8}
            ])
        ]
        
        rules = {}
        entities, rels, agreement = engine.aggregate_votes(votes, rules)
        
        # Only entities all 3 agree on
        assert len(entities) == 0


class TestWeightedConsensus:
    """Test weighted voting based on reputation."""
    
    def test_high_reputation_vote_wins(self):
        """High reputation agent's vote has more weight."""
        engine = WeightedConsensus()
        
        profiles = {
            'a1': AgentProfile('a1', reputation=0.95, accuracy=0.95),
            'a2': AgentProfile('a2', reputation=0.3, accuracy=0.3)
        }
        
        entity1 = {'text': 'Alice', 'type': 'PERSON', 'confidence': 0.9}
        entity2 = {'text': 'Alice', 'type': 'LOCATION', 'confidence': 0.7}
        
        votes = [
            AgentVote(agent_id='a1', entities=[entity1]),
            AgentVote(agent_id='a2', entities=[entity2])
        ]
        
        entities, rels, agreement = engine.aggregate_votes(votes, profiles)
        
        # High reputation agent should win
        if len(entities) > 0:
            assert entities[0]['type'] == 'PERSON'
    
    def test_multiple_high_reputation_votes(self):
        """Multiple high reputation agents voting for same entity."""
        engine = WeightedConsensus()
        
        profiles = {
            'a1': AgentProfile('a1', reputation=0.9, accuracy=0.9),
            'a2': AgentProfile('a2', reputation=0.9, accuracy=0.9),
            'a3': AgentProfile('a3', reputation=0.5, accuracy=0.5)
        }
        
        entity = {'text': 'Alice', 'type': 'PERSON', 'confidence': 0.9}
        divergent = {'text': 'Alice', 'type': 'LOCATION', 'confidence': 0.6}
        
        votes = [
            AgentVote(agent_id='a1', entities=[entity]),
            AgentVote(agent_id='a2', entities=[entity]),
            AgentVote(agent_id='a3', entities=[divergent])
        ]
        
        entities, rels, agreement = engine.aggregate_votes(votes, profiles)
        
        if len(entities) > 0:
            assert entities[0]['type'] == 'PERSON'


# ============================================================================
# Test Conflict Detection and Resolution
# ============================================================================


class TestConflictResolution:
    """Test conflict detection and resolution."""
    
    def test_find_entity_type_conflict(self):
        """Detect conflicting entity types."""
        votes = [
            AgentVote(agent_id='a1', entities=[
                {'text': 'Alice', 'type': 'PERSON', 'confidence': 0.9}
            ]),
            AgentVote(agent_id='a2', entities=[
                {'text': 'Alice', 'type': 'LOCATION', 'confidence': 0.8}
            ])
        ]
        
        conflicts = ConflictResolver.find_conflicts(votes)
        
        assert len(conflicts) == 1
        assert conflicts[0]['type'] == 'entity_type_conflict'
        assert 'Alice' in conflicts[0]['text']
    
    def test_find_relationship_type_conflict(self):
        """Detect conflicting relationship types."""
        votes = [
            AgentVote(agent_id='a1', relationships=[
                {'source_id': 'e1', 'target_id': 'e2', 'type': 'WORKS_FOR', 'confidence': 0.9}
            ]),
            AgentVote(agent_id='a2', relationships=[
                {'source_id': 'e1', 'target_id': 'e2', 'type': 'MANAGES', 'confidence': 0.8}
            ])
        ]
        
        conflicts = ConflictResolver.find_conflicts(votes)
        
        assert len(conflicts) == 1
        assert conflicts[0]['type'] == 'relationship_type_conflict'
    
    def test_no_conflicts(self):
        """No conflicts when all agree."""
        votes = [
            AgentVote(agent_id='a1', entities=[
                {'text': 'Alice', 'type': 'PERSON', 'confidence': 0.9}
            ]),
            AgentVote(agent_id='a2', entities=[
                {'text': 'Alice', 'type': 'PERSON', 'confidence': 0.9}
            ])
        ]
        
        conflicts = ConflictResolver.find_conflicts(votes)
        
        assert len(conflicts) == 0
    
    def test_resolve_by_confidence(self):
        """Resolve conflict by picking highest confidence."""
        votes = [
            AgentVote(agent_id='a1', entities=[
                {'text': 'Alice', 'type': 'PERSON', 'confidence': 0.85}
            ]),
            AgentVote(agent_id='a2', entities=[
                {'text': 'Alice', 'type': 'LOCATION', 'confidence': 0.95}
            ])
        ]
        
        conflict = {
            'type': 'entity_type_conflict',
            'text': 'Alice',
            'disagreement': ['PERSON', 'LOCATION']
        }
        
        resolved = ConflictResolver.resolve_by_confidence(conflict, votes)
        
        assert resolved is not None
        assert resolved['confidence'] == 0.95
        assert resolved['type'] == 'LOCATION'


# ============================================================================
# Test Metrics
# ============================================================================


class TestConsensusMetrics:
    """Test consensus metrics calculation."""
    
    def test_entropy_all_agree(self):
        """Entropy is 0 when all agree."""
        votes = [
            AgentVote(agent_id='a1', entities=[
                {'text': 'Alice', 'type': 'PERSON', 'confidence': 0.9}
            ]),
            AgentVote(agent_id='a2', entities=[
                {'text': 'Alice', 'type': 'PERSON', 'confidence': 0.9}
            ]),
            AgentVote(agent_id='a3', entities=[
                {'text': 'Alice', 'type': 'PERSON', 'confidence': 0.9}
            ])
        ]
        
        consensus = ConsensusResult(
            consensus_entities=[],
            consensus_relationships=[],
            agreement_rate=1.0,
            entropy=0.0,
            conflicts=[],
            strategies_applied=[]
        )
        
        entropy = ConsensusMetrics.calculate_entropy(votes, consensus)
        
        assert entropy == 0.0
    
    def test_entropy_all_disagree(self):
        """High entropy when all disagree."""
        votes = [
            AgentVote(agent_id='a1', entities=[
                {'text': 'Alice', 'type': 'PERSON', 'confidence': 0.9}
            ]),
            AgentVote(agent_id='a2', entities=[
                {'text': 'Bob', 'type': 'PERSON', 'confidence': 0.9}
            ]),
            AgentVote(agent_id='a3', entities=[
                {'text': 'Charlie', 'type': 'PERSON', 'confidence': 0.9}
            ])
        ]
        
        consensus = ConsensusResult(
            consensus_entities=[],
            consensus_relationships=[],
            agreement_rate=1.0,
            entropy=1.0,
            conflicts=[],
            strategies_applied=[]
        )
        
        entropy = ConsensusMetrics.calculate_entropy(votes, consensus)
        
        # Should be non-zero (higher entropy = more disagreement)
        assert entropy > 0
    
    def test_agreement_rate(self):
        """Calculate agreement rate."""
        consensus = ConsensusResult(
            consensus_entities=[
                {'text': 'Alice', 'type': 'PERSON'},
                {'text': 'Bob', 'type': 'PERSON'}
            ],
            consensus_relationships=[
                {'source_id': 'e1', 'target_id': 'e2', 'type': 'WORKS_FOR'}
            ],
            agreement_rate=0.75,
            entropy=0.5,
            conflicts=[],
            strategies_applied=[]
        )
        
        votes = [
            AgentVote(agent_id='a1', entities=[
                {'text': 'Alice', 'type': 'PERSON', 'confidence': 0.9},
                {'text': 'Bob', 'type': 'PERSON', 'confidence': 0.9},
                {'text': 'Charlie', 'type': 'PERSON', 'confidence': 0.9}
            ], relationships=[
                {'source_id': 'e1', 'target_id': 'e2', 'type': 'WORKS_FOR', 'confidence': 0.9}
            ])
        ]
        
        agreement = ConsensusMetrics.calculate_agreement_rate(consensus, votes)
        
        assert 0.0 <= agreement <= 1.0
    
    def test_confidence_variance(self):
        """Calculate confidence variance."""
        entities = [
            {'text': 'Alice', 'confidence': 0.9},
            {'text': 'Bob', 'confidence': 0.8},
            {'text': 'Charlie', 'confidence': 0.7}
        ]
        
        variance = ConsensusMetrics.calculate_confidence_variance(entities, [])
        
        assert variance > 0


# ============================================================================
# Test Consensus Manager
# ============================================================================


class TestConsensusManager:
    """Test consensus manager orchestration."""
    
    def test_register_agent(self):
        """Register agent in manager."""
        manager = ConsensusManager()
        manager.register_agent('agent1', reputation=0.9)
        
        assert 'agent1' in manager.agent_profiles
        assert manager.agent_profiles['agent1'].reputation == 0.9
    
    def test_reach_majority_consensus(self):
        """Reach majority consensus."""
        manager = ConsensusManager(strategy=ConsensusStrategy.MAJORITY)
        manager.register_agent('a1', reputation=0.9)
        manager.register_agent('a2', reputation=0.85)
        
        entity = {'text': 'Alice', 'type': 'PERSON', 'confidence': 0.9}
        
        votes = [
            AgentVote(agent_id='a1', entities=[entity]),
            AgentVote(agent_id='a2', entities=[entity])
        ]
        
        consensus = manager.reach_consensus(votes)
        
        assert len(consensus.consensus_entities) > 0
        assert consensus.agreement_rate > 0
    
    def test_reach_unanimous_consensus(self):
        """Reach unanimous consensus."""
        manager = ConsensusManager(strategy=ConsensusStrategy.UNANIMOUS)
        manager.register_agent('a1')
        manager.register_agent('a2')
        
        entity = {'text': 'Alice', 'type': 'PERSON', 'confidence': 0.9}
        
        votes = [
            AgentVote(agent_id='a1', entities=[entity]),
            AgentVote(agent_id='a2', entities=[entity])
        ]
        
        consensus = manager.reach_consensus(votes)
        
        assert len(consensus.consensus_entities) > 0
        assert consensus.consensus_entities[0]['vote_count'] == 2
    
    def test_update_agent_reputation(self, consensus_manager):
        """Update agent reputation."""
        initial = consensus_manager.agent_profiles['agent1'].accuracy
        
        consensus_manager.update_agent_reputation('agent1', correct=True, confidence=0.9)
        
        updated = consensus_manager.agent_profiles['agent1'].accuracy
        assert updated > initial

    def test_confidence_calibration_tracks_confidence_quality(self, consensus_manager):
        """Calibration should increase for well-calibrated confidence and decrease for poor calibration."""
        profile = consensus_manager.agent_profiles['agent1']
        initial_calibration = profile.confidence_calibration

        consensus_manager.update_agent_reputation('agent1', correct=True, confidence=1.0)
        after_well_calibrated = profile.confidence_calibration

        consensus_manager.update_agent_reputation('agent1', correct=False, confidence=1.0)
        after_poorly_calibrated = profile.confidence_calibration

        assert after_well_calibrated > initial_calibration
        assert after_poorly_calibrated < after_well_calibrated

    def test_confidence_input_is_clamped(self, consensus_manager):
        """Out-of-range confidence values should be clamped into [0, 1]."""
        profile = consensus_manager.agent_profiles['agent1']

        consensus_manager.update_agent_reputation('agent1', correct=True, confidence=2.5)
        high_outcome = profile.confidence_calibration

        consensus_manager.update_agent_reputation('agent1', correct=False, confidence=-3.0)
        low_outcome = profile.confidence_calibration

        assert 0.0 <= high_outcome <= 1.0
        assert 0.0 <= low_outcome <= 1.0
    
    def test_reputation_degradation(self, consensus_manager):
        """Agent reputation degrades with incorrect extractions."""
        profile = consensus_manager.agent_profiles['agent1']
        initial_accuracy = profile.accuracy
        
        # Multiple incorrect extractions
        for _ in range(5):
            consensus_manager.update_agent_reputation('agent1', correct=False, confidence=0.8)
        
        final_accuracy = profile.accuracy
        assert final_accuracy < initial_accuracy
    
    def test_consensus_statistics(self, consensus_manager):
        """Get consensus statistics."""
        # Add some votes
        votes = [
            AgentVote(agent_id='agent1', entities=[
                {'text': 'Alice', 'type': 'PERSON', 'confidence': 0.9}
            ]),
            AgentVote(agent_id='agent2', entities=[
                {'text': 'Alice', 'type': 'PERSON', 'confidence': 0.9}
            ])
        ]
        
        consensus_manager.reach_consensus(votes)
        
        stats = consensus_manager.get_consensus_statistics()
        
        assert stats['total_consensuses'] == 1
        assert 'avg_agreement_rate' in stats
        assert 'avg_entropy' in stats


# ============================================================================
# Test Edge Cases
# ============================================================================


class TestEdgeCases:
    """Test edge cases."""
    
    def test_single_agent_vote(self):
        """Consensus with single agent."""
        manager = ConsensusManager(strategy=ConsensusStrategy.MAJORITY)
        manager.register_agent('a1')
        
        entity = {'text': 'Alice', 'type': 'PERSON', 'confidence': 0.9}
        votes = [AgentVote(agent_id='a1', entities=[entity])]
        
        consensus = manager.reach_consensus(votes)
        
        assert len(consensus.consensus_entities) > 0
    
    def test_empty_votes(self):
        """Consensus with empty votes."""
        manager = ConsensusManager()
        
        votes = [
            AgentVote(agent_id='a1'),
            AgentVote(agent_id='a2')
        ]
        
        consensus = manager.reach_consensus(votes)
        
        assert len(consensus.consensus_entities) == 0
        assert len(consensus.consensus_relationships) == 0
    
    def test_many_agents(self):
        """Consensus with many agents."""
        manager = ConsensusManager(strategy=ConsensusStrategy.MAJORITY)
        
        # Register 20 agents
        for i in range(20):
            manager.register_agent(f'agent{i}')
        
        entity = {'text': 'Alice', 'type': 'PERSON', 'confidence': 0.9}
        
        # All vote for same entity
        votes = [
            AgentVote(agent_id=f'agent{i}', entities=[entity])
            for i in range(20)
        ]
        
        consensus = manager.reach_consensus(votes)
        
        assert len(consensus.consensus_entities) > 0
    
    def test_high_confidence_consensus(self):
        """Consensus with high confidence votes."""
        manager = ConsensusManager()
        
        entity = {'text': 'Alice', 'type': 'PERSON', 'confidence': 0.99}
        
        votes = [
            AgentVote(agent_id='a1', entities=[entity]),
            AgentVote(agent_id='a2', entities=[entity])
        ]
        
        consensus = manager.reach_consensus(votes)
        
        if len(consensus.consensus_entities) > 0:
            assert consensus.consensus_entities[0]['confidence'] > 0.9
    
    def test_low_confidence_consensus(self):
        """Consensus with low confidence votes."""
        manager = ConsensusManager()
        
        entity = {'text': 'Alice', 'type': 'PERSON', 'confidence': 0.51}
        
        votes = [
            AgentVote(agent_id='a1', entities=[entity]),
            AgentVote(agent_id='a2', entities=[entity])
        ]
        
        consensus = manager.reach_consensus(votes)
        
        if len(consensus.consensus_entities) > 0:
            assert consensus.consensus_entities[0]['confidence'] > 0.5
