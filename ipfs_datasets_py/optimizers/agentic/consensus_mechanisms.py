"""
Multi-Agent Consensus Mechanisms - Batch 247 [agentic].

Consensus system for multiple extraction agents reaching agreement on entities,
relationships, and overall extraction quality.

Architecture:
    - Agent voting: Multiple agents vote on extracted entities/relationships
    - Consensus strategies: Majority, unanimous, weighted voting, etc.
    - Conflict resolution: Handling disagreements between agents
    - Confidence aggregation: Combining agent confidences
    - Reputation system: Track agent accuracy over time
    - Consensus metrics: Measure agreement quality

Components:
    - AgentVote: Individual agent vote on extraction
    - ConsensusStrategy: Abstract strategy for consensus
    - MajorityConsensus: Simple majority voting
    - UnanimousConsensus: Requires all agents agree
    - WeightedConsensus: Weighted voting by agent reputation
    - ConflictResolver: Resolve disagreements
    - ConsensusManager: Orchestrate multi-agent consensus

Features:
    - Voting on extracted entities
    - Voting on relationships
    - Confidence calculation from votes
    - Agent reputation tracking
    - Conflict detection and resolution
    - Metrics (agreement rate, entropy, etc.)
    - Fallback strategies
    - Vote history tracking

Performance:
    - Consensus with 5-10 agents: ~100-500ms
    - Vote aggregation: ~1-10ms
    - Confidence calculation: ~1-5ms

Usage Example:
    >>> manager = ConsensusManager(strategy='weighted')
    >>> manager.register_agent('agent1', reputation=0.95)
    >>> manager.register_agent('agent2', reputation=0.90)
    >>> votes = [
    ...     AgentVote(agent_id='agent1', extractions={...}),
    ...     AgentVote(agent_id='agent2', extractions={...})
    ... ]
    >>> consensus = manager.reach_consensus(votes)
"""

from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
import math
from collections import Counter, defaultdict


# ============================================================================
# Core Data Structures
# ============================================================================


class ConsensusStrategy(Enum):
    """Available consensus strategies."""
    MAJORITY = "majority"  # >50% agreement required
    UNANIMOUS = "unanimous"  # 100% agreement required
    WEIGHTED = "weighted"  # Weighted by agent reputation
    THRESHOLD = "threshold"  # Configurable threshold
    QUALIFIED_MAJORITY = "qualified_majority"  # 2/3 majority


@dataclass
class AgentVote:
    """Single agent's vote on extractions."""
    agent_id: str
    entities: List[Dict[str, Any]] = field(default_factory=list)
    relationships: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.5  # Agent's overall confidence
    timestamp: Optional[str] = None


@dataclass
class ConsensusResult:
    """Result of consensus process."""
    consensus_entities: List[Dict[str, Any]]
    consensus_relationships: List[Dict[str, Any]]
    agreement_rate: float  # 0.0-1.0
    entropy: float  # Measure of disagreement
    conflicts: List[Dict[str, Any]]
    strategies_applied: List[str]


@dataclass
class AgentProfile:
    """Profile for tracking agent reputation."""
    agent_id: str
    reputation: float = 0.5  # 0.0-1.0
    accuracy: float = 0.5
    votes_count: int = 0
    correct_extractions: int = 0
    total_extractions: int = 0
    confidence_calibration: float = 0.5  # How well agent calibrates confidence


# ============================================================================
# Consensus Strategies
# ============================================================================


class ConsensusEngine(ABC):
    """Abstract consensus engine."""
    
    @abstractmethod
    def aggregate_votes(
        self,
        votes: List[AgentVote],
        agent_profiles: Dict[str, AgentProfile]
    ) -> Tuple[List[Dict], List[Dict], float]:
        """
        Aggregate votes into consensus.
        
        Returns:
            Tuple of (consensus_entities, consensus_relationships, agreement_rate)
        """
        pass


class MajorityConsensus(ConsensusEngine):
    """Simple majority voting (>50%)."""

    def _aggregate_with_threshold(
        self,
        votes: List[AgentVote],
        threshold: float,
    ) -> Tuple[List[Dict], List[Dict], float]:
        """Aggregate entities/relationships requiring at least *threshold* votes."""
        if not votes:
            return [], [], 0.0
    
        # Aggregate entities
        entity_votes = defaultdict(list)
        for vote in votes:
            for entity in vote.entities:
                key = (entity.get('text'), entity.get('type'))
                entity_votes[key].append(entity)
        
        consensus_entities = []
        for (text, entity_type), entity_list in entity_votes.items():
            if len(entity_list) >= threshold:
                # Average confidence
                avg_confidence = sum(e.get('confidence', 0) for e in entity_list) / len(entity_list)
                consensus_entities.append({
                    'text': text,
                    'type': entity_type,
                    'confidence': avg_confidence,
                    'vote_count': len(entity_list)
                })
        
        # Aggregate relationships
        rel_votes = defaultdict(list)
        for vote in votes:
            for rel in vote.relationships:
                key = (rel.get('source_id'), rel.get('target_id'), rel.get('type'))
                rel_votes[key].append(rel)
        
        consensus_relationships = []
        for (src, tgt, rel_type), rel_list in rel_votes.items():
            if len(rel_list) >= threshold:
                avg_confidence = sum(r.get('confidence', 0) for r in rel_list) / len(rel_list)
                consensus_relationships.append({
                    'source_id': src,
                    'target_id': tgt,
                    'type': rel_type,
                    'confidence': avg_confidence,
                    'vote_count': len(rel_list)
                })
        
        # Calculate agreement rate
        total_consensus = len(consensus_entities) + len(consensus_relationships)
        total_votes = sum(len(v.entities) + len(v.relationships) for v in votes)
        agreement_rate = total_consensus / total_votes if total_votes > 0 else 0.0

        return consensus_entities, consensus_relationships, agreement_rate

    def aggregate_votes(
        self,
        votes: List[AgentVote],
        agent_profiles: Dict[str, AgentProfile]
    ) -> Tuple[List[Dict], List[Dict], float]:
        """Majority voting consensus."""
        threshold = len(votes) / 2 + 0.1  # >50%
        return self._aggregate_with_threshold(votes, threshold)


class UnanimousConsensus(ConsensusEngine):
    """Unanimous voting (100% agreement)."""
    
    def aggregate_votes(
        self,
        votes: List[AgentVote],
        agent_profiles: Dict[str, AgentProfile]
    ) -> Tuple[List[Dict], List[Dict], float]:
        """Unanimous consensus - requires all agents agree."""
        n_agents = len(votes)
        
        # Find entities all agents agree on
        entity_votes = defaultdict(int)
        for vote in votes:
            for entity in vote.entities:
                key = (entity.get('text'), entity.get('type'))
                entity_votes[key] += 1
        
        consensus_entities = []
        for (text, entity_type), count in entity_votes.items():
            if count == n_agents:
                # Get averaged confidence
                confidences = []
                for vote in votes:
                    for entity in vote.entities:
                        if entity.get('text') == text and entity.get('type') == entity_type:
                            confidences.append(entity.get('confidence', 0))
                
                avg_confidence = sum(confidences) / len(confidences) if confidences else 0
                consensus_entities.append({
                    'text': text,
                    'type': entity_type,
                    'confidence': avg_confidence,
                    'vote_count': n_agents
                })
        
        # Find relationships all agents agree on
        rel_votes = defaultdict(int)
        for vote in votes:
            for rel in vote.relationships:
                key = (rel.get('source_id'), rel.get('target_id'), rel.get('type'))
                rel_votes[key] += 1
        
        consensus_relationships = []
        for (src, tgt, rel_type), count in rel_votes.items():
            if count == n_agents:
                confidences = []
                for vote in votes:
                    for rel in vote.relationships:
                        if (rel.get('source_id') == src and
                            rel.get('target_id') == tgt and
                            rel.get('type') == rel_type):
                            confidences.append(rel.get('confidence', 0))
                
                avg_confidence = sum(confidences) / len(confidences) if confidences else 0
                consensus_relationships.append({
                    'source_id': src,
                    'target_id': tgt,
                    'type': rel_type,
                    'confidence': avg_confidence,
                    'vote_count': n_agents
                })
        
        total_possible = sum(len(v.entities) + len(v.relationships) for v in votes)
        total_consensus = len(consensus_entities) + len(consensus_relationships)
        agreement_rate = total_consensus / total_possible if total_possible > 0 else 0.0
        
        return consensus_entities, consensus_relationships, agreement_rate


class ThresholdConsensus(MajorityConsensus):
    """Configurable threshold voting (fraction of agents)."""

    def __init__(self, threshold_fraction: float = 0.6):
        if not (0.0 < threshold_fraction <= 1.0):
            raise ValueError("threshold_fraction must be in (0, 1]")
        self.threshold_fraction = threshold_fraction

    def aggregate_votes(
        self,
        votes: List[AgentVote],
        agent_profiles: Dict[str, AgentProfile]
    ) -> Tuple[List[Dict], List[Dict], float]:
        threshold = len(votes) * self.threshold_fraction
        return self._aggregate_with_threshold(votes, threshold)


class QualifiedMajorityConsensus(ThresholdConsensus):
    """Qualified majority voting requiring two-thirds agreement."""

    def __init__(self):
        super().__init__(threshold_fraction=2.0 / 3.0)


class WeightedConsensus(ConsensusEngine):
    """Weighted voting based on agent reputation."""
    
    def aggregate_votes(
        self,
        votes: List[AgentVote],
        agent_profiles: Dict[str, AgentProfile]
    ) -> Tuple[List[Dict], List[Dict], float]:
        """Weighted consensus using agent reputation."""
        # Calculate weight for each agent
        weights = {}
        total_weight = 0
        for vote in votes:
            profile = agent_profiles.get(vote.agent_id)
            if profile:
                weight = profile.reputation * profile.accuracy
            else:
                weight = 0.5  # Default weight
            
            weights[vote.agent_id] = weight
            total_weight += weight
        
        # Normalize weights
        if total_weight > 0:
            weights = {aid: w / total_weight for aid, w in weights.items()}
        elif weights:
            uniform_weight = 1.0 / len(weights)
            weights = {aid: uniform_weight for aid in weights}
        
        # Weighted entity aggregation
        entity_weighted_votes = defaultdict(float)
        entity_list_map = defaultdict(list)
        
        for vote in votes:
            weight = weights.get(vote.agent_id, 0.5)
            for entity in vote.entities:
                key = (entity.get('text'), entity.get('type'))
                entity_weighted_votes[key] += weight
                entity_list_map[key].append(entity)
        
        threshold = 0.5  # >50% of weight
        consensus_entities = []
        for key, weighted_count in entity_weighted_votes.items():
            if weighted_count >= threshold:
                text, entity_type = key
                entities = entity_list_map[key]
                avg_confidence = sum(e.get('confidence', 0) for e in entities) / len(entities)
                
                consensus_entities.append({
                    'text': text,
                    'type': entity_type,
                    'confidence': avg_confidence,
                    'weighted_vote_count': weighted_count
                })
        
        # Weighted relationship aggregation
        rel_weighted_votes = defaultdict(float)
        rel_list_map = defaultdict(list)
        
        for vote in votes:
            weight = weights.get(vote.agent_id, 0.5)
            for rel in vote.relationships:
                key = (rel.get('source_id'), rel.get('target_id'), rel.get('type'))
                rel_weighted_votes[key] += weight
                rel_list_map[key].append(rel)
        
        consensus_relationships = []
        for key, weighted_count in rel_weighted_votes.items():
            if weighted_count >= threshold:
                src, tgt, rel_type = key
                rels = rel_list_map[key]
                avg_confidence = sum(r.get('confidence', 0) for r in rels) / len(rels)
                
                consensus_relationships.append({
                    'source_id': src,
                    'target_id': tgt,
                    'type': rel_type,
                    'confidence': avg_confidence,
                    'weighted_vote_count': weighted_count
                })
        
        total_consensus = len(consensus_entities) + len(consensus_relationships)
        total_votes = sum(1 for v in votes for _ in v.entities + v.relationships)
        agreement_rate = total_consensus / total_votes if total_votes > 0 else 0.0
        
        return consensus_entities, consensus_relationships, agreement_rate


# ============================================================================
# Conflict Resolution
# ============================================================================


class ConflictResolver:
    """Resolve disagreements between agents."""
    
    @staticmethod
    def find_conflicts(
        votes: List[AgentVote]
    ) -> List[Dict[str, Any]]:
        """Find entities/relationships with conflicting votes."""
        conflicts = []
        
        # Check entity conflicts
        entity_by_text = defaultdict(list)
        for vote in votes:
            for entity in vote.entities:
                text = entity.get('text')
                entity_type = entity.get('type')
                if text is None or entity_type is None:
                    continue
                entity_by_text[text].append({
                    'agent_id': vote.agent_id,
                    'entity': entity
                })
        
        for text, agents_data in entity_by_text.items():
            types = set(a['entity'].get('type') for a in agents_data)
            if len(types) > 1:
                conflicts.append({
                    'type': 'entity_type_conflict',
                    'text': text,
                    'disagreement': list(types),
                    'agents': [a['agent_id'] for a in agents_data]
                })
        
        # Check relationship conflicts
        rel_by_endpoints = defaultdict(list)
        for vote in votes:
            for rel in vote.relationships:
                src = rel.get('source_id')
                tgt = rel.get('target_id')
                rel_type = rel.get('type')
                if src is None or tgt is None or rel_type is None:
                    continue
                key = (src, tgt)
                rel_by_endpoints[key].append({
                    'agent_id': vote.agent_id,
                    'relationship': rel
                })
        
        for (src, tgt), agents_data in rel_by_endpoints.items():
            types = set(a['relationship'].get('type') for a in agents_data)
            if len(types) > 1:
                conflicts.append({
                    'type': 'relationship_type_conflict',
                    'source': src,
                    'target': tgt,
                    'disagreement': list(types),
                    'agents': [a['agent_id'] for a in agents_data]
                })
        
        return conflicts
    
    @staticmethod
    def resolve_by_confidence(
        conflict: Dict[str, Any],
        votes: List[AgentVote]
    ) -> Optional[Any]:
        """Resolve conflict by picking highest confidence vote."""
        if conflict['type'] == 'entity_type_conflict':
            best_entity = None
            best_confidence = -1
            
            for vote in votes:
                for entity in vote.entities:
                    if entity.get('text') == conflict['text']:
                        conf = entity.get('confidence', 0)
                        if conf > best_confidence:
                            best_confidence = conf
                            best_entity = entity
            
            return best_entity
        
        elif conflict['type'] == 'relationship_type_conflict':
            best_rel = None
            best_confidence = -1
            
            for vote in votes:
                for rel in vote.relationships:
                    if (rel.get('source_id') == conflict['source'] and
                        rel.get('target_id') == conflict['target']):
                        conf = rel.get('confidence', 0)
                        if conf > best_confidence:
                            best_confidence = conf
                            best_rel = rel
            
            return best_rel
        
        return None


# ============================================================================
# Consensus Metrics
# ============================================================================


class ConsensusMetrics:
    """Calculate consensus quality metrics."""
    
    @staticmethod
    def calculate_entropy(
        votes: List[AgentVote],
        consensus: Optional[ConsensusResult] = None
    ) -> float:
        """
        Calculate Shannon entropy of votes.
        
        Higher entropy = more disagreement
        0 = perfect agreement, 1 = maximum disagreement
        """
        total_extractions = sum(len(v.entities) + len(v.relationships) for v in votes)
        
        if total_extractions == 0:
            return 0.0
        
        # Build extraction frequencies across both entities and relationships.
        # This produces a bounded normalized entropy regardless of how many
        # extractions each vote contributes.
        extraction_frequencies = Counter()
        for vote in votes:
            for entity in vote.entities:
                key = ("entity", entity.get('text'), entity.get('type'))
                extraction_frequencies[key] += 1
            for rel in vote.relationships:
                key = (
                    "relationship",
                    rel.get('source_id'),
                    rel.get('target_id'),
                    rel.get('type'),
                )
                extraction_frequencies[key] += 1

        if not extraction_frequencies:
            return 0.0
        
        # Calculate entropy
        entropy = 0.0
        for count in extraction_frequencies.values():
            p = count / total_extractions
            if p > 0:
                entropy -= p * math.log2(p)
        
        # Normalize to [0,1] using the maximum entropy for observed classes.
        max_entropy = math.log2(len(extraction_frequencies)) if len(extraction_frequencies) > 1 else 0.0
        normalized_entropy = entropy / max_entropy if max_entropy > 0 else 0.0
        
        return normalized_entropy
    
    @staticmethod
    def calculate_agreement_rate(
        consensus: ConsensusResult,
        votes: List[AgentVote]
    ) -> float:
        """Calculate percentage of extractions in consensus."""
        total = sum(len(v.entities) + len(v.relationships) for v in votes)
        consensus_count = len(consensus.consensus_entities) + len(consensus.consensus_relationships)
        
        return consensus_count / total if total > 0 else 0.0
    
    @staticmethod
    def calculate_confidence_variance(
        consensus_entities: List[Dict],
        consensus_relationships: List[Dict]
    ) -> float:
        """Calculate variance in consensus confidences."""
        confidences = [
            e.get('confidence', 0) for e in consensus_entities
        ] + [
            r.get('confidence', 0) for r in consensus_relationships
        ]
        
        if not confidences:
            return 0.0
        
        mean = sum(confidences) / len(confidences)
        variance = sum((c - mean) ** 2 for c in confidences) / len(confidences)
        
        return math.sqrt(variance)  # Standard deviation


# ============================================================================
# Consensus Manager
# ============================================================================


class ConsensusManager:
    """Orchestrate multi-agent consensus process."""
    
    def __init__(
        self,
        strategy: ConsensusStrategy = ConsensusStrategy.WEIGHTED,
        threshold_fraction: float = 0.6,
    ):
        """
        Initialize consensus manager.
        
        Args:
            strategy: Consensus strategy to use
        """
        self.strategy = strategy
        self.agent_profiles: Dict[str, AgentProfile] = {}
        self.vote_history: List[ConsensusResult] = []
        
        # Select consensus engine
        if strategy == ConsensusStrategy.MAJORITY:
            self.engine = MajorityConsensus()
        elif strategy == ConsensusStrategy.UNANIMOUS:
            self.engine = UnanimousConsensus()
        elif strategy == ConsensusStrategy.THRESHOLD:
            self.engine = ThresholdConsensus(threshold_fraction=threshold_fraction)
        elif strategy == ConsensusStrategy.QUALIFIED_MAJORITY:
            self.engine = QualifiedMajorityConsensus()
        elif strategy == ConsensusStrategy.WEIGHTED:
            self.engine = WeightedConsensus()
        else:
            self.engine = MajorityConsensus()  # Default
    
    def register_agent(
        self,
        agent_id: str,
        reputation: float = 0.5,
        accuracy: float = 0.5
    ):
        """Register an agent."""
        self.agent_profiles[agent_id] = AgentProfile(
            agent_id=agent_id,
            reputation=reputation,
            accuracy=accuracy
        )
    
    def reach_consensus(self, votes: List[AgentVote]) -> ConsensusResult:
        """
        Reach consensus from multiple agent votes.
        
        Args:
            votes: List of agent votes
            
        Returns:
            Consensus result
        """
        # Aggregate votes using selected engine
        entities, relationships, agreement_rate = self.engine.aggregate_votes(
            votes, self.agent_profiles
        )
        
        # Find conflicts
        conflicts = ConflictResolver.find_conflicts(votes)
        
        # Calculate entropy
        entropy = ConsensusMetrics.calculate_entropy(votes)
        
        # Create result
        result = ConsensusResult(
            consensus_entities=entities,
            consensus_relationships=relationships,
            agreement_rate=agreement_rate,
            entropy=entropy,
            conflicts=conflicts,
            strategies_applied=[self.strategy.value]
        )
        
        # Store in history
        self.vote_history.append(result)
        
        return result
    
    def update_agent_reputation(
        self,
        agent_id: str,
        correct: bool,
        confidence: float
    ):
        """Update agent reputation based on feedback."""
        if agent_id not in self.agent_profiles:
            return
        
        profile = self.agent_profiles[agent_id]
        profile.votes_count += 1
        profile.total_extractions += 1
        
        if correct:
            profile.correct_extractions += 1
        
        # Update accuracy
        profile.accuracy = profile.correct_extractions / profile.total_extractions

        # Update confidence calibration from confidence error vs actual outcome.
        # 1.0 means confidence aligned with correctness, 0.0 means maximally off.
        confidence = max(0.0, min(1.0, confidence))
        target = 1.0 if correct else 0.0
        calibration_score = 1.0 - abs(confidence - target)
        profile.confidence_calibration = (
            (profile.confidence_calibration * (profile.votes_count - 1) + calibration_score)
            / profile.votes_count
        )
        
        # Update reputation (70% accuracy, 30% calibration)
        profile.reputation = 0.7 * profile.accuracy + 0.3 * profile.confidence_calibration
    
    def get_consensus_statistics(self) -> Dict[str, Any]:
        """Get overall consensus statistics."""
        if not self.vote_history:
            return {}
        
        agreement_rates = [r.agreement_rate for r in self.vote_history]
        entropies = [r.entropy for r in self.vote_history]
        
        return {
            'total_consensuses': len(self.vote_history),
            'avg_agreement_rate': sum(agreement_rates) / len(agreement_rates),
            'avg_entropy': sum(entropies) / len(entropies),
            'min_entropy': min(entropies),
            'max_entropy': max(entropies),
            'avg_conflicts': sum(len(r.conflicts) for r in self.vote_history) / len(self.vote_history)
        }
