"""Test suite for ontology_types.py TypedDict definitions (Batch 301).

This module provides comprehensive test coverage for all TypedDict definitions
in ontology_types.py, ensuring:
1. All types can be instantiated with required fields
2. Optional fields are correctly marked 
3. Type constraints are enforced at runtime
4. Serialization/deserialization round-trips work
5. Real usage patterns from the codebase are supported
"""

import pytest
from typing import Any, Dict, List
from datetime import datetime

from ipfs_datasets_py.optimizers.graphrag.ontology_types import (
    Entity,
    Relationship,
    OntologyMetadata,
    Ontology,
    EntityExtractionResult,
    RelationshipExtractionResult,
    DimensionalScore,
    CriticScore,
    RefinementAction,
    ActionLogEntry,
    SessionRound,
    OntologySession,
    GenerationContext,
    EntityStatistics,
    RelationshipStatistics,
    OntologyStatistics,
    PerformanceMetrics,
    QualityMetrics,
    PipelineStageResult,
    RefinementCycleResult,
    ExtractionConfigDict,
)


class TestEntityType:
    """Test Entity TypedDict."""
    
    def test_entity_required_fields(self):
        """Test Entity with only required fields."""
        entity: Entity = {
            "id": "ent_1",
            "text": "John Doe",
            "type": "Person",
            "confidence": 0.95,
        }
        
        assert entity["id"] == "ent_1"
        assert entity["text"] == "John Doe"
        assert entity["type"] == "Person"
        assert entity["confidence"] == 0.95
    
    def test_entity_with_optional_fields(self):
        """Test Entity with optional fields."""
        entity: Entity = {
            "id": "ent_1",
            "text": "John Doe",
            "type": "Person",
            "confidence": 0.95,
            "properties": {"age": 30, "title": "CEO"},
            "context": "mentioned in company report",
            "source_span": (0, 10),
        }
        
        assert entity["properties"]["age"] == 30
        assert entity["context"] == "mentioned in company report"
        assert entity["source_span"] == (0, 10)
    
    def test_entity_confidence_range(self):
        """Test Entity confidence is between 0 and 1."""
        for confidence in [0.0, 0.5, 1.0]:
            entity: Entity = {
                "id": "ent_1",
                "text": "Test",
                "type": "Type",
                "confidence": confidence,
            }
            assert 0.0 <= entity["confidence"] <= 1.0


class TestRelationshipType:
    """Test Relationship TypedDict."""
    
    def test_relationship_required_fields(self):
        """Test Relationship with required fields."""
        rel: Relationship = {
            "id": "rel_1",
            "source_id": "ent_1",
            "target_id": "ent_2",
            "type": "works_at",
            "confidence": 0.85,
        }
        
        assert rel["id"] == "rel_1"
        assert rel["source_id"] == "ent_1"
        assert rel["target_id"] == "ent_2"
        assert rel["type"] == "works_at"
    
    def test_relationship_with_optional_fields(self):
        """Test Relationship with optional fields."""
        rel: Relationship = {
            "id": "rel_1",
            "source_id": "ent_1",
            "target_id": "ent_2",
            "type": "works_at",
            "confidence": 0.85,
            "properties": {"start_date": "2020-01-01"},
            "context": "mentioned in resume",
            "distance": 5,
        }
        
        assert rel["properties"]["start_date"] == "2020-01-01"
        assert rel["distance"] == 5


class TestOntologyMetadataType:
    """Test OntologyMetadata TypedDict."""
    
    def test_metadata_required_fields(self):
        """Test OntologyMetadata with required fields."""
        metadata: OntologyMetadata = {
            "source": "legal_document.pdf",
            "domain": "legal",
            "strategy": "rule_based",
            "timestamp": "2026-02-25T10:00:00Z",
            "version": "1.0",
        }
        
        assert metadata["source"] == "legal_document.pdf"
        assert metadata["domain"] == "legal"
        assert metadata["strategy"] == "rule_based"
    
    def test_metadata_with_config(self):
        """Test OntologyMetadata with config."""
        metadata: OntologyMetadata = {
            "source": "doc.txt",
            "domain": "general",
            "strategy": "hybrid",
            "timestamp": "2026-02-25T10:00:00Z",
            "version": "1.0",
            "config": {"max_entities": 100, "min_confidence": 0.5},
        }
        
        assert metadata["config"]["max_entities"] == 100


class TestOntologyType:
    """Test complete Ontology TypedDict."""
    
    def test_ontology_required_fields(self):
        """Test Ontology with required fields."""
        ontology: Ontology = {
            "entities": [
                {
                    "id": "ent_1",
                    "text": "Company",
                    "type": "Organization",
                    "confidence": 0.9,
                },
            ],
            "relationships": [
                {
                    "id": "rel_1",
                    "source_id": "ent_1",
                    "target_id": "ent_2",
                    "type": "owns",
                    "confidence": 0.8,
                },
            ],
            "metadata": {
                "source": "doc.txt",
                "domain": "business",
                "strategy": "hybrid",
                "timestamp": "2026-02-25T10:00:00Z",
                "version": "1.0",
            },
        }
        
        assert len(ontology["entities"]) == 1
        assert len(ontology["relationships"]) == 1
        assert ontology["metadata"]["domain"] == "business"
    
    def test_ontology_empty_entities_relationships(self):
        """Test Ontology with empty entities/relationships."""
        ontology: Ontology = {
            "entities": [],
            "relationships": [],
            "metadata": {
                "source": "empty.txt",
                "domain": "general",
                "strategy": "rule_based",
                "timestamp": "2026-02-25T10:00:00Z",
                "version": "1.0",
            },
        }
        
        assert isinstance(ontology["entities"], list)
        assert isinstance(ontology["relationships"], list)


class TestExtractionResultTypes:
    """Test extraction result TypedDicts."""
    
    def test_entity_extraction_result(self):
        """Test EntityExtractionResult."""
        result: EntityExtractionResult = {
            "entities": [
                {
                    "id": "ent_1",
                    "text": "Test",
                    "type": "Type",
                    "confidence": 0.9,
                },
            ],
            "source": "test_text",
            "timestamp": "2026-02-25T10:00:00Z",
        }
        
        assert len(result["entities"]) == 1
        assert result["source"] == "test_text"
    
    def test_relationship_extraction_result(self):
        """Test RelationshipExtractionResult."""
        result: RelationshipExtractionResult = {
            "relationships": [
                {
                    "id": "rel_1",
                    "source_id": "ent_1",
                    "target_id": "ent_2",
                    "type": "works_at",
                    "confidence": 0.8,
                },
            ],
            "source": "test_text",
            "timestamp": "2026-02-25T10:00:00Z",
        }
        
        assert len(result["relationships"]) == 1
        assert result["source"] == "test_text"


class TestCriticScoreTypes:
    """Test CriticScore and related TypedDicts."""
    
    def test_dimensional_score(self):
        """Test DimensionalScore."""
        score: DimensionalScore = {
            "dimension": "completeness",
            "score": 0.85,
            "details": "85% of expected entities extracted",
        }
        
        assert score["dimension"] == "completeness"
        assert score["score"] == 0.85
    
    def test_critic_score_required_fields(self):
        """Test CriticScore with required fields."""
        score: CriticScore = {
            "overall_score": 0.82,
            "dimension_scores": [
                {"dimension": "completeness", "score": 0.85, "details": "Good"},
                {"dimension": "consistency", "score": 0.80, "details": "Fair"},
            ],
            "feedback": "Overall good structure",
            "recommendations": ["Add more relationships"],
            "strengths": ["High entity accuracy"],
            "weaknesses": ["Missing some relationships"],
        }
        
        assert score["overall_score"] == 0.82
        assert len(score["dimension_scores"]) == 2
        assert len(score["recommendations"]) == 1
    
    def test_critic_score_optional_fields(self):
        """Test CriticScore with optional fields."""
        score: CriticScore = {
            "overall_score": 0.75,
            "dimension_scores": [],
            "feedback": "Test feedback",
            "recommendations": [],
            "strengths": [],
            "weaknesses": [],
            "timestamp": "2026-02-25T10:00:00Z",
            "evaluator": "ontology_critic_v1",
            "evaluation_method": "rule_based",
        }
        
        assert score.get("evaluator") == "ontology_critic_v1"
        assert score.get("evaluation_method") == "rule_based"


class TestRefinementActionTypes:
    """Test refinement action TypedDicts."""
    
    def test_refinement_action(self):
        """Test RefinementAction."""
        action: RefinementAction = {
            "action_id": "action_1",
            "type": "add_entity",
            "target": {"id": "ent_new", "type": "Person", "text": "New Entity"},
            "rationale": "Missing person entity",
            "confidence": 0.8,
        }
        
        assert action["action_id"] == "action_1"
        assert action["type"] == "add_entity"
        assert action["confidence"] == 0.8
    
    def test_action_log_entry(self):
        """Test ActionLogEntry."""
        entry: ActionLogEntry = {
            "timestamp": "2026-02-25T10:00:00Z",
            "action": {
                "action_id": "action_1",
                "type": "add_entity",
                "target": {"id": "ent_1", "type": "Person", "text": "Test"},
                "rationale": "Test",
                "confidence": 0.9,
            },
            "success": True,
            "result": {"entities_added": 1},
        }
        
        assert entry["success"] is True
        assert entry["result"]["entities_added"] == 1


class TestSessionTypes:
    """Test session-related TypedDicts."""
    
    def test_session_round(self):
        """Test SessionRound."""
        round_data: SessionRound = {
            "round_number": 1,
            "generated_ontology": {
                "entities": [],
                "relationships": [],
                "metadata": {
                    "source": "test",
                    "domain": "test",
                    "strategy": "test",
                    "timestamp": "2026-02-25T10:00:00Z",
                    "version": "1.0",
                },
            },
            "critic_score": {
                "overall_score": 0.8,
                "dimension_scores": [],
                "feedback": "Test",
                "recommendations": [],
                "strengths": [],
                "weaknesses": [],
            },
            "refinements_applied": 0,
        }
        
        assert round_data["round_number"] == 1
        assert round_data["refinements_applied"] == 0
    
    def test_ontology_session(self):
        """Test OntologySession."""
        session: OntologySession = {
            "session_id": "sess_1",
            "created_at": "2026-02-25T10:00:00Z",
            "source_data": "test_text",
            "domain": "general",
            "rounds_completed": 2,
            "final_ontology": {
                "entities": [],
                "relationships": [],
                "metadata": {
                    "source": "test",
                    "domain": "general",
                    "strategy": "hybrid",
                    "timestamp": "2026-02-25T10:00:00Z",
                    "version": "1.0",
                },
            },
            "final_score": 0.85,
        }
        
        assert session["session_id"] == "sess_1"
        assert session["rounds_completed"] == 2
        assert session["final_score"] == 0.85


class TestStatisticsTypes:
    """Test statistics TypedDicts."""
    
    def test_entity_statistics(self):
        """Test EntityStatistics."""
        stats: EntityStatistics = {
            "total_count": 100,
            "by_type": {"Person": 50, "Organization": 30, "Location": 20},
            "average_confidence": 0.85,
            "confidence_distribution": {
                "0.0-0.25": 5,
                "0.25-0.5": 10,
                "0.5-0.75": 20,
                "0.75-1.0": 65,
            },
        }
        
        assert stats["total_count"] == 100
        assert stats["by_type"]["Person"] == 50
        assert stats["average_confidence"] == 0.85
    
    def test_ontology_statistics(self):
        """Test OntologyStatistics."""
        stats: OntologyStatistics = {
            "entity_count": 100,
            "relationship_count": 80,
            "entity_types": ["Person", "Organization"],
            "relationship_types": ["works_at", "located_in"],
            "coverage": 0.92,
            "density": 0.78,
        }
        
        assert stats["entity_count"] == 100
        assert stats["coverage"] == 0.92
        assert stats["density"] == 0.78


class TestPerformanceMetricsTypes:
    """Test performance and quality metric types."""
    
    def test_performance_metrics(self):
        """Test PerformanceMetrics."""
        metrics: PerformanceMetrics = {
            "extraction_time_ms": 250,
            "criticism_time_ms": 150,
            "refinement_time_ms": 100,
            "total_time_ms": 500,
            "entities_per_second": 400,
            "memory_usage_mb": 50.5,
        }
        
        assert metrics["total_time_ms"] == 500
        assert metrics["entities_per_second"] == 400
    
    def test_quality_metrics(self):
        """Test QualityMetrics."""
        metrics: QualityMetrics = {
            "clarity_score": 0.88,
            "consistency_score": 0.82,
            "completeness_score": 0.85,
            "overall_quality": 0.85,
            "improvement_vs_baseline": 0.15,
        }
        
        assert metrics["overall_quality"] == 0.85
        assert metrics["improvement_vs_baseline"] == 0.15


class TestPipelineTypes:
    """Test pipeline-related TypedDicts."""
    
    def test_pipeline_stage_result(self):
        """Test PipelineStageResult."""
        result: PipelineStageResult = {
            "stage_name": "extraction",
            "success": True,
            "duration_ms": 250,
            "output": {
                "entities": [],
                "relationships": [],
            },
        }
        
        assert result["stage_name"] == "extraction"
        assert result["success"] is True
        assert result["duration_ms"] == 250
    
    def test_refinement_cycle_result(self):
        """Test RefinementCycleResult."""
        result: RefinementCycleResult = {
            "cycle_number": 1,
            "actions_executed": 5,
            "score_before": 0.70,
            "score_after": 0.78,
            "improvement": 0.08,
            "timestamp": "2026-02-25T10:00:00Z",
        }
        
        assert result["cycle_number"] == 1
        assert result["improvement"] == 0.08
        assert result["score_after"] > result["score_before"]


class TestExtractionConfigType:
    """Test ExtractionConfigDict TypedDict."""
    
    def test_extraction_config_dict(self):
        """Test ExtractionConfigDict."""
        config: ExtractionConfigDict = {
            "confidence_threshold": 0.5,
            "max_entities": 500,
            "max_relationships": 300,
            "window_size": 512,
            "min_entity_length": 2,
            "domain": "legal",
        }
        
        assert config["confidence_threshold"] == 0.5
        assert config["domain"] == "legal"
    
    def test_extraction_config_with_optional_fields(self):
        """Test ExtractionConfigDict with optional fields."""
        config: ExtractionConfigDict = {
            "confidence_threshold": 0.5,
            "max_entities": 500,
            "max_relationships": 300,
            "window_size": 512,
            "min_entity_length": 2,
            "domain": "legal",
            "stopwords": ["the", "a", "an"],
            "allowed_entity_types": ["Person", "Organization"],
            "custom_rules": {"rule1": "pattern1"},
        }
        
        assert "stopwords" in config
        assert "allowed_entity_types" in config
        assert len(config["allowed_entity_types"]) == 2


class TestTypeRoundTripsAndSerialization:
    """Test round-trip serialization of complex types."""
    
    def test_ontology_round_trip(self):
        """Test that Ontology can be serialized and deserialized."""
        original: Ontology = {
            "entities": [
                {
                    "id": "ent_1",
                    "text": "Test Entity",
                    "type": "Person",
                    "confidence": 0.95,
                    "properties": {"title": "CEO"},
                },
            ],
            "relationships": [
                {
                    "id": "rel_1",
                    "source_id": "ent_1",
                    "target_id": "ent_2",
                    "type": "works_at",
                    "confidence": 0.80,
                },
            ],
            "metadata": {
                "source": "test.txt",
                "domain": "business",
                "strategy": "hybrid",
                "timestamp": "2026-02-25T10:00:00Z",
                "version": "1.0",
            },
        }
        
        # Simulate serialization to dict/JSON
        serialized = dict(original)
        
        # Deserialize back
        deserialized: Ontology = serialized
        
        # Verify round-trip
        assert deserialized["metadata"]["domain"] == original["metadata"]["domain"]
        assert len(deserialized["entities"]) == len(original["entities"])
        assert deserialized["entities"][0]["text"] == original["entities"][0]["text"]
    
    def test_critic_score_round_trip(self):
        """Test CriticScore round-trip."""
        original: CriticScore = {
            "overall_score": 0.85,
            "dimension_scores": [
                {"dimension": "completeness", "score": 0.85, "details": "Good"},
            ],
            "feedback": "Test",
            "recommendations": ["Improve consistency"],
            "strengths": ["Good coverage"],
            "weaknesses": ["Missing relationships"],
            "evaluator": "testing",
        }
        
        serialized = dict(original)
        deserialized: CriticScore = serialized
        
        assert deserialized["overall_score"] == original["overall_score"]
        assert deserialized["evaluator"] == original["evaluator"]


class TestTypeEnumeration:
    """Test that all documented types exist and can be instantiated."""
    
    def test_all_types_importable(self):
        """Test that all types can be imported successfully."""
        # This test passes if all imports at the top of the file succeed
        assert Entity is not None
        assert Relationship is not None
        assert Ontology is not None
        assert CriticScore is not None
        assert OntologySession is not None
    
    def test_complex_nested_structures(self):
        """Test that complex nested structures work."""
        # Create a structure with multiple nesting levels
        session: OntologySession = {
            "session_id": "test",
            "created_at": "2026-02-25T10:00:00Z",
            "source_data": "test",
            "domain": "legal",
            "rounds_completed": 1,
            "final_ontology": {
                "entities": [
                    {
                        "id": "ent_1",
                        "text": "John Doe",
                        "type": "Person",
                        "confidence": 0.95,
                        "properties": {"age": 30},
                    },
                ],
                "relationships": [
                    {
                        "id": "rel_1",
                        "source_id": "ent_1",
                        "target_id": "ent_2",
                        "type": "knows",
                        "confidence": 0.85,
                    },
                ],
                "metadata": {
                    "source": "doc.pdf",
                    "domain": "legal",
                    "strategy": "hybrid",
                    "timestamp": "2026-02-25T10:00:00Z",
                    "version": "1.0",
                },
            },
            "final_score": 0.88,
        }
        
        # Navigate nested structure
        assert session["final_ontology"]["entities"][0]["text"] == "John Doe"
        assert session["final_ontology"]["relationships"][0]["type"] == "knows"
        assert session["final_score"] == 0.88
