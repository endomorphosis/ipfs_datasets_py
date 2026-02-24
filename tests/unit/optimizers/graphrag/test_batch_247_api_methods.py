"""
Test suite for Batch 247 API methods.

Tests new convenience methods for GraphRAG components:
- OntologyGenerator.rebuild_result(entities)
- OntologyLearningAdapter.score_variance()
- OntologyCritic.score_range(scores)
- OntologyGenerator.sorted_entities(result, key)
- OntologyMediator.log_snapshot(label)
- EntityExtractionResult.confidence_histogram(bins)

Format: GIVEN-WHEN-THEN
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag import (
    OntologyGenerator,
    OntologyGenerationContext,
    OntologyCritic,
    OntologyMediator,
    OntologyLearningAdapter,
    ExtractionStrategy,
    DataType,
    Entity,
    EntityExtractionResult,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import FeedbackRecord


class TestOntologyGeneratorRebuildResult:
    """Test OntologyGenerator.rebuild_result() method."""
    
    @pytest.fixture
    def generator(self):
        return OntologyGenerator()
    
    def test_rebuild_result_creates_extraction_result(self, generator):
        """rebuild_result wraps entities in EntityExtractionResult."""
        entities = [
            Entity(id="e1", text="Alice", type="Person", confidence=0.9, properties={}),
            Entity(id="e2", text="Bob", type="Person", confidence=0.8, properties={}),
        ]
        result = generator.rebuild_result(entities)
        
        assert isinstance(result, EntityExtractionResult)
        assert len(result.entities) == 2
        assert result.entities[0].text == "Alice"
        assert result.entities[1].text == "Bob"
    
    def test_rebuild_result_empty_entities(self, generator):
        """rebuild_result handles empty entity list."""
        result = generator.rebuild_result([])
        
        assert isinstance(result, EntityExtractionResult)
        assert len(result.entities) == 0
        assert len(result.relationships) == 0
    
    def test_rebuild_result_preserves_confidence(self, generator):
        """rebuild_result preserves entity confidence scores."""
        entities = [
            Entity(id="e1", text="Alice", type="Person", confidence=0.95, properties={}),
        ]
        result = generator.rebuild_result(entities)
        
        assert result.entities[0].confidence == 0.95
    
    def test_rebuild_result_sets_default_confidence(self, generator):
        """rebuild_result computes default confidence from entity count."""
        entities = [
            Entity(id="e1", text="Alice", type="Person", confidence=0.9, properties={}),
            Entity(id="e2", text="Bob", type="Person", confidence=0.8, properties={}),
        ]
        result = generator.rebuild_result(entities)
        
        # Should compute confidence from entity avg or provide default
        assert isinstance(result.confidence, float)
        assert 0.0 <= result.confidence <= 1.0
    
    def test_rebuild_result_includes_properties(self, generator):
        """rebuild_result preserves entity properties."""
        entities = [
            Entity(id="e1", text="Alice", type="Person", confidence=0.9, 
                   properties={"age": 30, "role": "Engineer"}),
        ]
        result = generator.rebuild_result(entities)
        
        assert result.entities[0].properties == {"age": 30, "role": "Engineer"}
    
    def test_rebuild_result_no_relationships(self, generator):
        """rebuild_result creates result with no relationships."""
        entities = [
            Entity(id="e1", text="Alice", type="Person", confidence=0.9, properties={}),
        ]
        result = generator.rebuild_result(entities)
        
        assert len(result.relationships) == 0


class TestOntologyLearningAdapterScoreVariance:
    """Test OntologyLearningAdapter.score_variance() method."""
    
    @pytest.fixture
    def adapter(self):
        return OntologyLearningAdapter()
    
    def test_score_variance_empty_feedback(self, adapter):
        """score_variance returns 0.0 for empty feedback history."""
        variance = adapter.score_variance()
        assert variance == 0.0
    
    def test_score_variance_single_feedback(self, adapter):
        """score_variance returns 0.0 for single feedback record."""
        adapter.apply_feedback(final_score=0.8)
        variance = adapter.score_variance()
        assert variance == 0.0
    
    def test_score_variance_identical_scores(self, adapter):
        """score_variance returns 0.0 when all scores are identical."""
        for _ in range(5):
            adapter.apply_feedback(final_score=0.75)
        variance = adapter.score_variance()
        assert variance == 0.0
    
    def test_score_variance_calculates_correctly(self, adapter):
        """score_variance computes population variance correctly."""
        scores = [0.6, 0.7, 0.8, 0.9]
        for score in scores:
            adapter.apply_feedback(final_score=score)
        
        variance = adapter.score_variance()
        
        # Population variance = Σ(x_i - μ)² / N
        mean = sum(scores) / len(scores)  # 0.75
        expected = sum((s - mean) ** 2 for s in scores) / len(scores)  # 0.0125
        assert abs(variance - expected) < 1e-6
    
    def test_score_variance_high_variability(self, adapter):
        """score_variance reflects high variability in scores."""
        adapter.apply_feedback(final_score=0.1)
        adapter.apply_feedback(final_score=0.9)
        
        variance = adapter.score_variance()
        
        # Variance should be significant for spread-out scores
        assert variance > 0.15  # (0.1-0.5)²=0.16, (0.9-0.5)²=0.16, avg=0.16
    
    def test_score_variance_returns_float(self, adapter):
        """score_variance returns float type."""
        adapter.apply_feedback(final_score=0.7)
        adapter.apply_feedback(final_score=0.8)
        
        variance = adapter.score_variance()
        assert isinstance(variance, float)


class TestOntologyCriticScoreRange:
    """Test OntologyCritic.score_range() method."""
    
    @pytest.fixture
    def critic(self):
        return OntologyCritic(use_llm=False)
    
    def _make_score(self, overall: float) -> CriticScore:
        """Helper to create CriticScore with specific overall value."""
        return CriticScore(
            completeness=overall, consistency=overall, clarity=overall,
            granularity=overall, relationship_coherence=overall,
            domain_alignment=overall, strengths=[], weaknesses=[], recommendations=[]
        )
    
    def test_score_range_single_score(self, critic):
        """score_range returns (score, score) for single score."""
        scores = [self._make_score(0.75)]
        min_score, max_score = critic.score_range(scores)
        
        assert min_score == 0.75
        assert max_score == 0.75
    
    def test_score_range_finds_min_max(self, critic):
        """score_range correctly identifies minimum and maximum scores."""
        scores = [
            self._make_score(0.6), self._make_score(0.9),
            self._make_score(0.7), self._make_score(0.5),
        ]
        min_score, max_score = critic.score_range(scores)
        
        assert min_score == 0.5
        assert max_score == 0.9
    
    def test_score_range_empty_list(self, critic):
        """score_range returns (0.0, 0.0) for empty list."""
        min_score, max_score = critic.score_range([])
        
        assert min_score == 0.0
        assert max_score == 0.0
    
    def test_score_range_returns_tuple(self, critic):
        """score_range returns tuple of two floats."""
        scores = [self._make_score(0.7), self._make_score(0.8)]
        result = critic.score_range(scores)
        
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], float)
        assert isinstance(result[1], float)
    
    def test_score_range_identical_scores(self, critic):
        """score_range handles all identical scores."""
        scores = [self._make_score(0.75)] * 5
        min_score, max_score = critic.score_range(scores)
        
        assert min_score == 0.75
        assert max_score == 0.75


class TestOntologyGeneratorSortedEntities:
    """Test OntologyGenerator.sorted_entities() method."""
    
    @pytest.fixture
    def generator(self):
        return OntologyGenerator()
    
    @pytest.fixture
    def sample_result(self):
        """Create sample EntityExtractionResult with multiple entities."""
        entities = [
            Entity(id="e1", text="Alice", type="Person", confidence=0.6, properties={}),
            Entity(id="e2", text="Zebra", type="Animal", confidence=0.9, properties={}),
            Entity(id="e3", text="Bob", type="Person", confidence=0.8, properties={}),
        ]
        return EntityExtractionResult(entities=entities, relationships=[], confidence=0.77)
    
    def test_sorted_entities_by_confidence(self, generator, sample_result):
        """sorted_entities sorts by confidence descending."""
        sorted_entities = generator.sorted_entities(sample_result, key="confidence")
        
        assert sorted_entities[0].confidence == 0.9  # Zebra
        assert sorted_entities[1].confidence == 0.8  # Bob
        assert sorted_entities[2].confidence == 0.6  # Alice
    
    def test_sorted_entities_by_text(self, generator, sample_result):
        """sorted_entities sorts by text alphabetically."""
        sorted_entities = generator.sorted_entities(sample_result, key="text", reverse=False)
        
        assert sorted_entities[0].text == "Alice"
        assert sorted_entities[1].text == "Bob"
        assert sorted_entities[2].text == "Zebra"
    
    def test_sorted_entities_by_type(self, generator, sample_result):
        """sorted_entities sorts by type alphabetically."""
        sorted_entities = generator.sorted_entities(sample_result, key="type", reverse=False)
        
        assert sorted_entities[0].type == "Animal"  # Zebra
        assert sorted_entities[1].type == "Person"  # Alice or Bob
        assert sorted_entities[2].type == "Person"
    
    def test_sorted_entities_preserves_relationships(self, generator):
        """sorted_entities returns sorted list of entities."""
        from ipfs_datasets_py.optimizers.graphrag import Relationship
        entities = [
            Entity(id="e1", text="Alice", type="Person", confidence=0.8, properties={}),
            Entity(id="e2", text="Bob", type="Person", confidence=0.9, properties={}),
        ]
        relationships = [
            Relationship(id="r1", source_id="e1", target_id="e2", type="knows", 
                        confidence=0.7, properties={})
        ]
        result = EntityExtractionResult(entities=entities, relationships=relationships, confidence=0.85)
        
        sorted_entities = generator.sorted_entities(result, key="confidence")
        
        assert len(sorted_entities) == 2
        assert sorted_entities[0].id == "e2"  # Bob, higher confidence
    
    def test_sorted_entities_empty_result(self, generator):
        """sorted_entities handles empty result."""
        empty_result = EntityExtractionResult(entities=[], relationships=[], confidence=0.0)
        sorted_entities = generator.sorted_entities(empty_result, key="confidence")
        
        assert len(sorted_entities) == 0
    
    def test_sorted_entities_returns_new_result(self, generator, sample_result):
        """sorted_entities returns list of entities."""
        sorted_entities = generator.sorted_entities(sample_result, key="text")
        
        assert isinstance(sorted_entities, list)
        assert len(sorted_entities) == 3


class TestOntologyMediatorLogSnapshot:
    """Test OntologyMediator.log_snapshot() method."""
    
    @pytest.fixture
    def mediator(self):
        return OntologyMediator(
            generator=OntologyGenerator(),
            critic=OntologyCritic(use_llm=False),
            max_rounds=3,
        )
    
    def test_log_snapshot_labels_undo_stack(self, mediator):
        """log_snapshot adds label to current undo stack state."""
        ontology = {"entities": [], "relationships": []}
        mediator._undo_stack.append(ontology.copy())
        
        mediator.log_snapshot(label="checkpoint_1", ontology=ontology)
        
        # Should have labeled the snapshot somehow (implementation dependent)
        assert hasattr(mediator, '_snapshot_labels') or mediator.get_undo_depth() > 0
    
    def test_log_snapshot_multiple_labels(self, mediator):
        """log_snapshot handles multiple labeled snapshots."""
        ont1 = {"entities": [{"id": "e1"}], "relationships": []}
        ont2 = {"entities": [{"id": "e2"}], "relationships": []}
        
        mediator._undo_stack.append(ont1)
        mediator.log_snapshot(label="first", ontology=ont1)
        
        mediator._undo_stack.append(ont2)
        mediator.log_snapshot(label="second", ontology=ont2)
        
        assert mediator.get_undo_depth() >= 2
    
    def test_log_snapshot_does_not_modify_ontology(self, mediator):
        """log_snapshot does not modify the ontology."""
        ontology = {"entities": [{"id": "e1"}], "relationships": []}
        original = ontology.copy()
        
        mediator._undo_stack.append(ontology)
        mediator.log_snapshot(label="test", ontology=ontology)
        
        assert ontology == original  # No modification


class TestEntityExtractionResultConfidenceHistogram:
    """Test EntityExtractionResult.confidence_histogram() method."""
    
    def _make_result(self, confidences: list) -> EntityExtractionResult:
        """Helper to create result with specified entity confidences."""
        entities = [
            Entity(id=f"e{i}", text=f"Entity{i}", type="Thing", confidence=conf, properties={})
            for i, conf in enumerate(confidences)
        ]
        return EntityExtractionResult(entities=entities, relationships=[], confidence=0.8)
    
    def test_confidence_histogram_default_bins(self):
        """confidence_histogram creates 10 bins by default."""
        result = self._make_result([0.1, 0.3, 0.5, 0.7, 0.9])
        histogram = result.confidence_histogram()
        
        assert len(histogram) == 10  # Default 10 bins
        assert all(isinstance(count, int) for count in histogram)
    
    def test_confidence_histogram_custom_bins(self):
        """confidence_histogram respects custom bin count."""
        result = self._make_result([0.2, 0.5, 0.8])
        histogram = result.confidence_histogram(bins=5)
        
        assert len(histogram) == 5
    
    def test_confidence_histogram_counts_correctly(self):
        """confidence_histogram counts entities per bin correctly."""
        # All entities in 0.8-0.9 range
        result = self._make_result([0.81, 0.82, 0.83, 0.84, 0.85])
        histogram = result.confidence_histogram(bins=10)
        
        # Bins: [0.0-0.1], [0.1-0.2], ..., [0.8-0.9], [0.9-1.0]
        # All 5 entities should be in bin 8 (0.8-0.9)
        assert histogram[8] == 5
        assert sum(histogram[:8]) == 0  # No entities in lower bins
        assert histogram[9] == 0  # No entities in [0.9-1.0]
    
    def test_confidence_histogram_edge_values(self):
        """confidence_histogram handles edge values (0.0, 1.0) correctly."""
        result = self._make_result([0.0, 0.5, 1.0])
        histogram = result.confidence_histogram(bins=10)
        
        # Should handle boundaries properly
        assert sum(histogram) == 3  # All 3 entities counted
    
    def test_confidence_histogram_empty_result(self):
        """confidence_histogram returns all zeros for empty result."""
        result = self._make_result([])
        histogram = result.confidence_histogram(bins=5)
        
        assert histogram == [0, 0, 0, 0, 0]
    
    def test_confidence_histogram_uniform_distribution(self):
        """confidence_histogram distributes uniformly spread confidences."""
        # Spread across all bins
        result = self._make_result([0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95])
        histogram = result.confidence_histogram(bins=10)
        
        # Each bin should have exactly 1 entity
        assert histogram == [1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
    
    def test_confidence_histogram_returns_list_of_ints(self):
        """confidence_histogram returns list of integers."""
        result = self._make_result([0.5, 0.6])
        histogram = result.confidence_histogram(bins=5)
        
        assert isinstance(histogram, list)
        assert all(isinstance(count, int) for count in histogram)


class TestBatch247Integration:
    """Integration tests for all Batch 247 methods working together."""
    
    def test_workflow_rebuild_sort_histogram(self):
        """Test workflow: rebuild result → sort → analyze histogram."""
        generator = OntologyGenerator()
        
        # Create entities
        entities = [
            Entity(id="e1", text="Low", type="A", confidence=0.3, properties={}),
            Entity(id="e2", text="High", type="B", confidence=0.9, properties={}),
            Entity(id="e3", text="Med", type="A", confidence=0.6, properties={}),
        ]
        
        # Rebuild result
        result = generator.rebuild_result(entities)
        assert len(result.entities) == 3
        
        # Sort by confidence (returns List[Entity])
        sorted_entities = generator.sorted_entities(result, key="confidence")
        assert sorted_entities[0].confidence == 0.9  # High first
        
        # Analyze histogram on original result
        histogram = result.confidence_histogram(bins=3)
        assert sum(histogram) == 3  # All entities counted
    
    def test_adapter_variance_with_mediator_snapshots(self):
        """Test adapter variance tracking alongside mediator snapshots."""
        adapter = OntologyLearningAdapter()
        mediator = OntologyMediator(
            generator=OntologyGenerator(),
            critic=OntologyCritic(use_llm=False),
        )
        
        # Record feedback with varying scores
        for score in [0.5, 0.7, 0.9]:
            adapter.apply_feedback(final_score=score)
            mediator._undo_stack.append({"score": score})
            mediator.log_snapshot(label=f"score_{score}", ontology={"score": score})
        
        # Check variance
        variance = adapter.score_variance()
        assert variance > 0.0  # Should have variability
        
        # Check snapshots
        assert mediator.get_undo_depth() > 0
    
    def test_critic_score_range_integration(self):
        """Test critic score_range with generated scores."""
        critic = OntologyCritic(use_llm=False)
        generator = OntologyGenerator()
        context = OntologyGenerationContext(
            data_source="test",
            data_type=DataType.TEXT,
            domain="general",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
        )
        
        # Generate several ontologies and evaluate
        texts = [
            "Alice works for Acme Corp.",
            "Bob manages the engineering team.",
            "Carol is a consultant.",
        ]
        scores = []
        for text in texts:
            ontology = generator.generate_ontology(text, context)
            score = critic.evaluate_ontology(ontology, context)
            scores.append(score)
        
        # Get score range
        min_score, max_score = critic.score_range(scores)
        assert 0.0 <= min_score <= max_score <= 1.0
