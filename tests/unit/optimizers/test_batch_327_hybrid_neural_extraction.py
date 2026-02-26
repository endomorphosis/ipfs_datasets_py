"""
Batch 327: Hybrid/Neural Extraction Strategies
==============================================

Implements hybrid and neural extraction strategies combining rule-based and
LLM-based approaches for improved entity extraction quality.

Goal: Provide:
- HybridExtractor combining rule-based and LLM-based approaches
- WeightedVoting for consensus-based extraction results
- EnsembleExtractor for combining multiple extraction strategies
- Neural-inspired confidence scoring
- Strategy evaluation and performance metrics
"""

import pytest
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict, field
from enum import Enum
from unittest.mock import Mock, MagicMock
import statistics


@dataclass
class ExtractionResult:
    """Result from an extraction strategy."""
    entities: List[Dict[str, Any]]
    confidence: float
    strategy: str
    execution_time_ms: float = 0.0
    error: Optional[str] = None
    
    def is_valid(self) -> bool:
        """Check if result is valid."""
        return self.error is None and len(self.entities) > 0


@dataclass
class HybridExtractionConfig:
    """Configuration for hybrid extraction."""
    use_rule_based: bool = True
    use_llm_based: bool = True
    use_neural: bool = False
    voting_strategy: str = "weighted"  # weighted, majority, unanimous
    confidence_threshold: float = 0.5
    aggregation_method: str = "consensus"  # consensus, union, intersection
    weights: Dict[str, float] = field(default_factory=lambda: {
        "rule_based": 1.0,
        "llm_based": 1.5,
        "neural": 2.0,
    })
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HybridExtractionConfig":
        """Create from dictionary."""
        return cls(**data)


class VotingStrategy:
    """Weighted voting for ensemble extraction."""
    
    def __init__(self, weights: Optional[Dict[str, float]] = None):
        """Initialize voting strategy.
        
        Args:
            weights: Weights for each strategy
        """
        self.weights = weights or {
            "rule_based": 1.0,
            "llm_based": 1.5,
            "neural": 2.0,
        }
        self.total_votes = 0
        self.vote_counts = {}
    
    def vote(self, strategy: str, entities: List[Dict[str, Any]]) -> None:
        """Cast a vote for entities from a strategy.
        
        Args:
            strategy: Strategy name
            entities: Extracted entities
        """
        weight = self.weights.get(strategy, 1.0)
        self.total_votes += weight
        
        for entity in entities:
            entity_id = entity.get("id", entity.get("text", "unknown"))
            key = f"{strategy}:{entity_id}"
            self.vote_counts[key] = self.vote_counts.get(key, 0) + weight
    
    def get_consensus(self, threshold: float = 0.5) -> List[Tuple[str, str, float]]:
        """Get entities with consensus above threshold.
        
        Returns:
            List of (strategy, entity_id, confidence) tuples
        """
        if self.total_votes == 0:
            return []
        
        consensus = []
        for key, votes in self.vote_counts.items():
            confidence = votes / self.total_votes
            if confidence >= threshold:
                strategy, entity_id = key.rsplit(":", 1)
                consensus.append((strategy, entity_id, confidence))
        
        return sorted(consensus, key=lambda x: x[2], reverse=True)


class NeuralConfidenceScorer:
    """Neural-inspired confidence scoring."""
    
    def __init__(self, hidden_dim: int = 64):
        """Initialize scorer.
        
        Args:
            hidden_dim: Hidden dimension size
        """
        self.hidden_dim = hidden_dim
        self.weights = {}
    
    def score(self, entity: Dict[str, Any], context_length: int) -> float:
        """Score entity confidence using neural-inspired approach.
        
        Args:
            entity: Entity dictionary
            context_length: Length of context
            
        Returns:
            Confidence score [0, 1]
        """
        # Neural-inspired scoring combining multiple factors
        base_confidence = entity.get("confidence", 0.5)
        
        # Length normalization
        text_len = len(entity.get("text", ""))
        length_factor = min(1.0, text_len / max(context_length, 1))
        
        # Type-specific weighting
        entity_type = entity.get("type", "unknown").lower()
        type_weights = {
            "entity": 1.0,
            "relation": 1.2,
            "attribute": 0.8,
            "event": 1.1,
        }
        type_factor = type_weights.get(entity_type, 1.0)
        
        # Combine factors with non-linear activation
        combined = base_confidence * length_factor * type_factor
        # Apply sigmoid-like squashing to keep in [0, 1]
        final_score = 1.0 / (1.0 + (1.0 - combined) / (combined + 0.0001))
        
        return max(0.0, min(1.0, final_score))


class HybridExtractor:
    """Hybrid extraction combining multiple strategies."""
    
    def __init__(self, config: Optional[HybridExtractionConfig] = None):
        """Initialize hybrid extractor.
        
        Args:
            config: Hybrid extraction configuration
        """
        self.config = config or HybridExtractionConfig()
        self.rule_based_extractor = None
        self.llm_based_extractor = None
        self.neural_extractor = None
        self.voting = VotingStrategy(self.config.weights)
        self.neural_scorer = NeuralConfidenceScorer()
        self.results_history = []
    
    def set_rule_based_extractor(self, extractor) -> None:
        """Set rule-based extraction strategy.
        
        Args:
            extractor: Rule-based extractor instance
        """
        self.rule_based_extractor = extractor
    
    def set_llm_based_extractor(self, extractor) -> None:
        """Set LLM-based extraction strategy.
        
        Args:
            extractor: LLM-based extractor instance
        """
        self.llm_based_extractor = extractor
    
    def set_neural_extractor(self, extractor) -> None:
        """Set neural extraction strategy.
        
        Args:
            extractor: Neural extractor instance
        """
        self.neural_extractor = extractor
    
    def extract(self, text: str, domain: str = "general") -> Dict[str, Any]:
        """Extract entities using hybrid strategy.
        
        Args:
            text: Input text
            domain: Domain specification
            
        Returns:
            Result dictionary
        """
        if not self.config.use_rule_based and not self.config.use_llm_based and not self.config.use_neural:
            return {"error": "No extraction strategies enabled"}
        
        results = []
        
        # Run enabled strategies
        if self.config.use_rule_based and self.rule_based_extractor:
            try:
                rule_result = self.rule_based_extractor.extract(text, domain)
                results.append(("rule_based", rule_result))
            except Exception as e:
                results.append(("rule_based", {"error": str(e), "entities": []}))
        
        if self.config.use_llm_based and self.llm_based_extractor:
            try:
                llm_result = self.llm_based_extractor.extract(text, domain)
                results.append(("llm_based", llm_result))
            except Exception as e:
                results.append(("llm_based", {"error": str(e), "entities": []}))
        
        if self.config.use_neural and self.neural_extractor:
            try:
                neural_result = self.neural_extractor.extract(text, domain)
                results.append(("neural", neural_result))
            except Exception as e:
                results.append(("neural", {"error": str(e), "entities": []}))
        
        # Aggregate results
        combined = self._aggregate_results(results, text)
        self.results_history.append(combined)
        
        return combined
    
    def _aggregate_results(self, results: List[Tuple[str, Dict]], text: str) -> Dict[str, Any]:
        """Aggregate results from multiple strategies.
        
        Args:
            results: List of (strategy_name, result) tuples
            text: Original input text
            
        Returns:
            Aggregated result dictionary
        """
        if self.config.aggregation_method == "union":
            return self._aggregate_union(results, text)
        elif self.config.aggregation_method == "intersection":
            return self._aggregate_intersection(results, text)
        else:  # consensus
            return self._aggregate_consensus(results, text)
    
    def _aggregate_union(self, results: List[Tuple[str, Dict]], text: str) -> Dict[str, Any]:
        """Combine all entities (union)."""
        all_entities = []
        seen_ids = set()
        
        for strategy_name, result in results:
            if result.get("error"):
                continue
            
            for entity in result.get("entities", []):
                entity_id = entity.get("id", entity.get("text"))
                if entity_id not in seen_ids:
                    seen_ids.add(entity_id)
                    entity["source_strategy"] = strategy_name
                    # Re-score with neural scorer
                    entity["confidence"] = self.neural_scorer.score(entity, len(text))
                    all_entities.append(entity)
        
        return {
            "success": len(all_entities) > 0,
            "entities": all_entities,
            "aggregation": "union",
            "strategies_used": [s[0] for s in results if not s[1].get("error")],
        }
    
    def _aggregate_intersection(self, results: List[Tuple[str, Dict]], text: str) -> Dict[str, Any]:
        """Keep only entities found by all strategies (intersection)."""
        if not results:
            return {"success": False, "entities": [], "aggregation": "intersection"}
        
        # Get entity maps from each strategy
        entity_maps = []
        for strategy_name, result in results:
            if result.get("error"):
                continue
            entity_map = {e.get("text", ""): e for e in result.get("entities", [])}
            entity_maps.append(entity_map)
        
        if not entity_maps:
            return {"success": False, "entities": [], "aggregation": "intersection"}
        
        # Find intersection (entities in all strategies)
        common_texts = set(entity_maps[0].keys())
        for entity_map in entity_maps[1:]:
            common_texts &= set(entity_map.keys())
        
        common_entities = [entity_maps[0][text] for text in common_texts]
        
        return {
            "success": len(common_entities) > 0,
            "entities": common_entities,
            "aggregation": "intersection",
            "strategies_used": [s[0] for s in results if not s[1].get("error")],
        }
    
    def _aggregate_consensus(self, results: List[Tuple[str, Dict]], text: str) -> Dict[str, Any]:
        """Aggregate using weighted voting (consensus)."""
        voting = VotingStrategy(self.config.weights)
        
        for strategy_name, result in results:
            if result.get("error"):
                continue
            voting.vote(strategy_name, result.get("entities", []))
        
        consensus = voting.get_consensus(self.config.confidence_threshold)
        
        # Build consensus entities
        consensus_entities = []
        entity_lookup = {}
        for strategy_name, result in results:
            if result.get("error"):
                continue
            for entity in result.get("entities", []):
                key = entity.get("id", entity.get("text"))
                if key not in entity_lookup:
                    entity_lookup[key] = entity
        
        for strategy, entity_id, confidence in consensus:
            entity = entity_lookup.get(entity_id)
            if entity:
                entity["consensus_confidence"] = confidence
                entity["consensus_strategy"] = strategy
                consensus_entities.append(entity)
        
        return {
            "success": len(consensus_entities) > 0,
            "entities": consensus_entities,
            "aggregation": "consensus",
            "consensus_votes": len(consensus),
            "strategies_used": [s[0] for s in results if not s[1].get("error")],
        }


class EnsembleExtractor:
    """Ensemble of multiple extraction strategies."""
    
    def __init__(self, extractors: Optional[Dict[str, Any]] = None):
        """Initialize ensemble.
        
        Args:
            extractors: Dictionary of strategy_name -> extractor instance
        """
        self.extractors = extractors or {}
        self.results_history = []
        self.performance_metrics = {}
    
    def add_extractor(self, name: str, extractor) -> None:
        """Add an extraction strategy.
        
        Args:
            name: Strategy name
            extractor: Extractor instance
        """
        self.extractors[name] = extractor
        self.performance_metrics[name] = {"success_count": 0, "failure_count": 0, "avg_entities": 0.0}
    
    def extract(self, text: str, domain: str = "general") -> Dict[str, Any]:
        """Extract using all strategies and aggregate.
        
        Args:
            text: Input text
            domain: Domain specification
            
        Returns:
            Aggregated result
        """
        results = {}
        entity_counts = []
        
        for strategy_name, extractor in self.extractors.items():
            try:
                result = extractor.extract(text, domain)
                results[strategy_name] = result
                entity_count = len(result.get("entities", []))
                entity_counts.append(entity_count)
                self.performance_metrics[strategy_name]["success_count"] += 1
                self.performance_metrics[strategy_name]["avg_entities"] = statistics.mean(
                    [self.performance_metrics[strategy_name].get("avg_entities", 0), entity_count]
                ) if entity_counts else 0
            except Exception as e:
                results[strategy_name] = {"error": str(e), "entities": []}
                self.performance_metrics[strategy_name]["failure_count"] += 1
        
        # Aggregate results
        all_entities = []
        entity_ids = set()
        
        for strategy_name, result in results.items():
            if result.get("error"):
                continue
            for entity in result.get("entities", []):
                entity_id = entity.get("id", entity.get("text"))
                if entity_id not in entity_ids:
                    entity_ids.add(entity_id)
                    entity["strategies"] = [strategy_name]
                    all_entities.append(entity)
                else:
                    # Update with additional strategy
                    for e in all_entities:
                        if e.get("id", e.get("text")) == entity_id:
                            e["strategies"].append(strategy_name)
                            break
        
        ensemble_result = {
            "success": len(all_entities) > 0,
            "entities": all_entities,
            "strategy_results": {k: len(v.get("entities", [])) for k, v in results.items()},
            "ensemble_size": len([r for r in results.values() if not r.get("error")]),
        }
        
        self.results_history.append(ensemble_result)
        return ensemble_result
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get ensemble performance summary.
        
        Returns:
            Performance metrics
        """
        return {
            "extractors": len(self.extractors),
            "metrics": self.performance_metrics,
            "total_extractions": len(self.results_history),
        }


# ============================================================================
# TEST CLASSES
# ============================================================================

class TestExtractionResult:
    """Test ExtractionResult data class."""
    
    def test_create_result(self):
        """Test creating result."""
        result = ExtractionResult(
            entities=[{"id": "e1"}],
            confidence=0.95,
            strategy="hybrid"
        )
        assert result.confidence == 0.95
        assert len(result.entities) == 1
    
    def test_result_validity(self):
        """Test result validity checks."""
        valid = ExtractionResult(entities=[{"id": "e1"}], confidence=0.9, strategy="test")
        assert valid.is_valid() is True
        
        invalid_error = ExtractionResult(entities=[], confidence=0.9, strategy="test", error="failed")
        assert invalid_error.is_valid() is False
        
        invalid_empty = ExtractionResult(entities=[], confidence=0.9, strategy="test")
        assert invalid_empty.is_valid() is False


class TestHybridExtractionConfig:
    """Test hybrid extraction configuration."""
    
    def test_default_config(self):
        """Test default configuration."""
        config = HybridExtractionConfig()
        assert config.use_rule_based is True
        assert config.use_llm_based is True
        assert config.use_neural is False
    
    def test_config_serialization(self):
        """Test config serialization."""
        config = HybridExtractionConfig(use_neural=True)
        d = config.to_dict()
        restored = HybridExtractionConfig.from_dict(d)
        assert restored.use_neural == config.use_neural


class TestVotingStrategy:
    """Test voting strategy."""
    
    def test_weighted_voting(self):
        """Test weighted voting."""
        weights = {"rule": 1.0, "llm": 2.0}
        voting = VotingStrategy(weights)
        
        voting.vote("rule", [{"id": "e1", "text": "entity"}])
        voting.vote("llm", [{"id": "e1", "text": "entity"}])
        
        consensus = voting.get_consensus(threshold=0.4)
        assert len(consensus) > 0
        # Entity should have higher confidence due to llm weight
        assert consensus[0][2] > 0.5  # Confidence from llm weight
    
    def test_consensus_threshold(self):
        """Test consensus threshold filtering."""
        voting = VotingStrategy({"s1": 1.0, "s2": 1.0})
        
        voting.vote("s1", [{"id": "e1"}])
        voting.vote("s2", [{"id": "e2"}])  # Different entity
        
        # Threshold of 0.5 - entities with 50% of votes should be included
        consensus = voting.get_consensus(threshold=0.5)
        assert len(consensus) == 2  # Both entities got exactly 50% of votes (0.5 confidence)
        
        # Higher threshold - no entities should pass
        consensus = voting.get_consensus(threshold=0.51)
        assert len(consensus) == 0  # No entity got >50% of votes


class TestNeuralConfidenceScorer:
    """Test neural confidence scorer."""
    
    def test_score_entity(self):
        """Test entity scoring."""
        scorer = NeuralConfidenceScorer()
        
        entity = {"text": "test entity", "type": "entity", "confidence": 0.8}
        score = scorer.score(entity, context_length=100)
        
        assert 0 <= score <= 1
    
    def test_type_weighting(self):
        """Test type-specific scoring."""
        scorer = NeuralConfidenceScorer()
        
        relation = {"text": "test", "type": "relation", "confidence": 0.8}
        attribute = {"text": "test", "type": "attribute", "confidence": 0.8}
        
        rel_score = scorer.score(relation, 100)
        attr_score = scorer.score(attribute, 100)
        
        # Relation should score higher
        assert rel_score > attr_score


class TestHybridExtractor:
    """Test hybrid extractor."""
    
    def test_hybrid_initialization(self):
        """Test initialization."""
        extractor = HybridExtractor()
        assert extractor.config.use_rule_based is True
        assert extractor.config.use_llm_based is True
    
    def test_no_strategies_enabled(self):
        """Test error when no strategies enabled."""
        config = HybridExtractionConfig(use_rule_based=False, use_llm_based=False, use_neural=False)
        extractor = HybridExtractor(config)
        
        result = extractor.extract("test")
        assert "error" in result
    
    def test_union_aggregation(self):
        """Test union aggregation."""
        config = HybridExtractionConfig(aggregation_method="union")
        extractor = HybridExtractor(config)
        
        # Mock extractors
        rule_extractor = Mock()
        rule_extractor.extract.return_value = {
            "entities": [{"id": "e1", "text": "entity1", "confidence": 0.8}]
        }
        
        llm_extractor = Mock()
        llm_extractor.extract.return_value = {
            "entities": [{"id": "e2", "text": "entity2", "confidence": 0.9}]
        }
        
        extractor.set_rule_based_extractor(rule_extractor)
        extractor.set_llm_based_extractor(llm_extractor)
        
        result = extractor.extract("test text")
        
        assert result["success"] is True
        assert len(result["entities"]) >= 2  # Union of both
        assert result["aggregation"] == "union"
    
    def test_intersection_aggregation(self):
        """Test intersection aggregation."""
        config = HybridExtractionConfig(aggregation_method="intersection")
        extractor = HybridExtractor(config)
        
        # Mock extractors with overlapping entities
        rule_extractor = Mock()
        rule_extractor.extract.return_value = {
            "entities": [
                {"id": "e1", "text": "shared", "confidence": 0.8},
                {"id": "e2", "text": "unique_rule", "confidence": 0.7},
            ]
        }
        
        llm_extractor = Mock()
        llm_extractor.extract.return_value = {
            "entities": [
                {"id": "e1", "text": "shared", "confidence": 0.9},
                {"id": "e3", "text": "unique_llm", "confidence": 0.8},
            ]
        }
        
        extractor.set_rule_based_extractor(rule_extractor)
        extractor.set_llm_based_extractor(llm_extractor)
        
        result = extractor.extract("test")
        
        assert result["aggregation"] == "intersection"
        # Only shared entities should be in result
        assert len(result["entities"]) <= 1


class TestEnsembleExtractor:
    """Test ensemble extractor."""
    
    def test_ensemble_initialization(self):
        """Test initialization."""
        ensemble = EnsembleExtractor()
        assert len(ensemble.extractors) == 0
    
    def test_add_extractors(self):
        """Test adding extractors."""
        ensemble = EnsembleExtractor()
        
        ext1 = Mock()
        ext2 = Mock()
        
        ensemble.add_extractor("rule", ext1)
        ensemble.add_extractor("llm", ext2)
        
        assert len(ensemble.extractors) == 2
    
    def test_ensemble_extraction(self):
        """Test ensemble extraction."""
        ensemble = EnsembleExtractor()
        
        # Mock extractors
        ext1 = Mock()
        ext1.extract.return_value = {
            "entities": [{"id": "e1", "text": "entity1"}]
        }
        
        ext2 = Mock()
        ext2.extract.return_value = {
            "entities": [{"id": "e1", "text": "entity1"}, {"id": "e2", "text": "entity2"}]
        }
        
        ensemble.add_extractor("strategy1", ext1)
        ensemble.add_extractor("strategy2", ext2)
        
        result = ensemble.extract("test")
        
        assert result["success"] is True
        assert result["ensemble_size"] == 2
        assert "strategy_results" in result
    
    def test_performance_summary(self):
        """Test performance summary."""
        ensemble = EnsembleExtractor()
        
        ext = Mock()
        ext.extract.return_value = {"entities": []}
        
        ensemble.add_extractor("test", ext)
        ensemble.extract("text")
        
        summary = ensemble.get_performance_summary()
        
        assert summary["extractors"] == 1
        assert summary["total_extractions"] == 1
        assert "metrics" in summary
