"""Batch 149: Pipeline description and reporting utilities.

Tests for human-readable extraction pipeline summaries and descriptions.
- ExtractionConfig.describe() — human-readable config summary
- OntologyGenerator.describe_extraction_pipeline() — comprehensive pipeline report
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    ExtractionConfig,
    EntityExtractionResult,
    Entity,
    Relationship,
    OntologyGenerator,
)


class TestExtractionConfigDescribe:
    """Test ExtractionConfig.describe() human-readable summaries."""

    def test_describe_returns_string(self):
        """describe() returns a string."""
        config = ExtractionConfig()
        result = config.describe()
        assert isinstance(result, str)

    def test_describe_includes_class_name(self):
        """describe() output starts with ExtractionConfig marker."""
        config = ExtractionConfig()
        result = config.describe()
        assert result.startswith("ExtractionConfig:")

    def test_describe_includes_threshold(self):
        """describe() includes confidence_threshold value."""
        config = ExtractionConfig(confidence_threshold=0.7)
        result = config.describe()
        assert "threshold=0.7" in result

    def test_describe_includes_max_entities(self):
        """describe() includes max_entities (or 'unlimited' if 0)."""
        config = ExtractionConfig(max_entities=100)
        result = config.describe()
        assert "max_entities=100" in result

    def test_describe_show_unlimited_for_zero_entities(self):
        """describe() shows 'unlimited' when max_entities is 0."""
        config = ExtractionConfig(max_entities=0)
        result = config.describe()
        assert "max_entities=unlimited" in result

    def test_describe_includes_window_size(self):
        """describe() includes window_size."""
        config = ExtractionConfig(window_size=10)
        result = config.describe()
        assert "window=10" in result

    def test_describe_includes_min_length(self):
        """describe() includes min_entity_length."""
        config = ExtractionConfig(min_entity_length=3)
        result = config.describe()
        assert "min_len=3" in result

    def test_describe_includes_max_confidence(self):
        """describe() includes max_confidence."""
        config = ExtractionConfig(max_confidence=0.95)
        result = config.describe()
        assert "max_conf=0.95" in result

    def test_describe_shows_llm_fallback_when_set(self):
        """describe() includes llm_fallback_threshold only when > 0."""
        config_with = ExtractionConfig(llm_fallback_threshold=0.5)
        result_with = config_with.describe()
        assert "llm_fallback=0.5" in result_with

        config_without = ExtractionConfig(llm_fallback_threshold=0.0)
        result_without = config_without.describe()
        assert "llm_fallback" not in result_without

    def test_describe_includes_stopword_count(self):
        """describe() shows stopword count when stopwords are configured."""
        config = ExtractionConfig(stopwords=["the", "a", "an"])
        result = config.describe()
        assert "stopwords=3" in result

    def test_describe_includes_entity_types(self):
        """describe() shows allowed_entity_types when configured."""
        config = ExtractionConfig(allowed_entity_types=["Person", "Organization", "Location"])
        result = config.describe()
        assert "types=" in result
        assert "Person" in result or "Organization" in result

    def test_describe_multiple_configs_different(self):
        """Different configs produce different descriptions."""
        config1 = ExtractionConfig(confidence_threshold=0.5)
        config2 = ExtractionConfig(confidence_threshold=0.8)
        desc1 = config1.describe()
        desc2 = config2.describe()
        assert desc1 != desc2
        assert "threshold=0.5" in desc1
        assert "threshold=0.8" in desc2

    def test_describe_handles_all_fields(self):
        """describe() handles all fields being non-default."""
        config = ExtractionConfig(
            confidence_threshold=0.75,
            max_entities=150,
            max_relationships=500,
            window_size=15,
            min_entity_length=3,
            max_confidence=0.98,
            llm_fallback_threshold=0.4,
            stopwords=["common", "word"],
            allowed_entity_types=["Person", "Org"],
        )
        result = config.describe()
        assert "threshold=0.75" in result
        assert "max_entities=150" in result
        assert "window=15" in result
        assert "min_len=3" in result
        assert "max_conf=0.98" in result
        assert "llm_fallback=0.4" in result
        assert "stopwords=2" in result
        assert "types=" in result


class TestOntologyGeneratorDescribeExtractionPipeline:
    """Test OntologyGenerator.describe_extraction_pipeline() reports."""

    @pytest.fixture
    def generator(self):
        """Provides an OntologyGenerator instance."""
        return OntologyGenerator()

    def test_describe_pipeline_config_only(self, generator):
        """describe_extraction_pipeline() works with config only."""
        config = ExtractionConfig(confidence_threshold=0.6)
        result = generator.describe_extraction_pipeline(config)
        assert isinstance(result, str)
        assert "ExtractionConfig:" in result

    def test_describe_pipeline_includes_config_description(self, generator):
        """Output includes config description."""
        config = ExtractionConfig(confidence_threshold=0.7, max_entities=100)
        result = generator.describe_extraction_pipeline(config)
        assert "threshold=0.7" in result
        assert "max_entities=100" in result

    def test_describe_pipeline_empty_result(self, generator):
        """describe_extraction_pipeline() handles empty extraction results."""
        config = ExtractionConfig()
        result = EntityExtractionResult(entities=[], relationships=[], confidence=0.0)
        summary = generator.describe_extraction_pipeline(config, result)
        assert "empty" in summary
        assert "0 entities" in summary
        assert "0 relationships" in summary

    def test_describe_pipeline_populated_result(self, generator):
        """describe_extraction_pipeline() includes result statistics."""
        config = ExtractionConfig(confidence_threshold=0.5)
        entities = [
            Entity(id="e1", type="Person", text="Alice", confidence=0.9),
            Entity(id="e2", type="Organization", text="Acme Corp", confidence=0.8),
        ]
        relationships = [
            Relationship(
                id="r1",
                source_id="e1",
                target_id="e2",
                type="works_for",
                confidence=0.75,
            )
        ]
        result = EntityExtractionResult(
            entities=entities,
            relationships=relationships,
            confidence=0.8,
        )
        summary = generator.describe_extraction_pipeline(config, result)
        assert "populated" in summary
        assert "2 entities" in summary
        assert "1 relationships" in summary
        assert "avg_conf=" in summary

    def test_describe_pipeline_multiline_output(self, generator):
        """Output is multiline when result is provided."""
        config = ExtractionConfig(confidence_threshold=0.6)
        entities = [Entity(id="e1", type="Person", text="Bob", confidence=0.85)]
        result = EntityExtractionResult(
            entities=entities, relationships=[], confidence=0.85
        )
        summary = generator.describe_extraction_pipeline(config, result)
        lines = summary.split("\n")
        assert len(lines) >= 2
        assert "ExtractionConfig:" in lines[0]
        assert "Extraction Result" in lines[1]

    def test_describe_pipeline_confidence_calculation(self, generator):
        """Average confidence is calculated correctly."""
        config = ExtractionConfig()
        entities = [
            Entity(id="e1", type="Person", text="Alice", confidence=0.9),
            Entity(id="e2", type="Person", text="Bob", confidence=0.8),
            Entity(id="e3", type="Person", text="Charlie", confidence=0.7),
        ]
        result = EntityExtractionResult(entities=entities, relationships=[], confidence=1.0)
        summary = generator.describe_extraction_pipeline(config, result)
        expected_avg = (0.9 + 0.8 + 0.7) / 3
        assert f"avg_conf=0.{int((expected_avg-0.8)*100)}" in summary or f"avg_conf=0.8" in summary

    def test_describe_pipeline_zero_entities_no_crash(self, generator):
        """describe_extraction_pipeline() handles zero entities gracefully."""
        config = ExtractionConfig()
        result = EntityExtractionResult(entities=[], relationships=[], confidence=0.0)
        summary = generator.describe_extraction_pipeline(config, result)
        assert "0 entities" in summary
        assert "avg_conf=0.00" in summary

    def test_describe_pipeline_large_result(self, generator):
        """describe_extraction_pipeline() scales to large results."""
        config = ExtractionConfig(max_entities=1000)
        entities = [
            Entity(id=f"e{i}", type="Person", text=f"Person{i}", confidence=0.7 + i * 0.0001)
            for i in range(100)
        ]
        relationships = [
            Relationship(
                id=f"r{i}",
                source_id=f"e{i}",
                target_id=f"e{(i+1)%100}",
                type="knows",
                confidence=0.6,
            )
            for i in range(50)
        ]
        result = EntityExtractionResult(
            entities=entities, relationships=relationships, confidence=0.75
        )
        summary = generator.describe_extraction_pipeline(config, result)
        assert "100 entities" in summary
        assert "50 relationships" in summary

    def test_describe_pipeline_only_none_result(self, generator):
        """describe_extraction_pipeline() works with None result."""
        config = ExtractionConfig(confidence_threshold=0.5)
        summary = generator.describe_extraction_pipeline(config, None)
        assert "ExtractionConfig:" in summary
        assert "Extraction Result" not in summary

    def test_describe_pipeline_preserves_config_order(self, generator):
        """describe_extraction_pipeline() preserves expected field order."""
        config = ExtractionConfig(
            confidence_threshold=0.7, window_size=8, min_entity_length=3
        )
        summary = generator.describe_extraction_pipeline(config)
        lines = summary.split("\n")
        config_line = lines[0]
        threshold_pos = config_line.find("threshold=0.7")
        window_pos = config_line.find("window=8")
        min_len_pos = config_line.find("min_len=3")
        assert threshold_pos < window_pos < min_len_pos


class TestPipelineDescriptionIntegration:
    """Integration tests for pipeline description utilities."""

    def test_describe_config_then_pipeline(self):
        """Can chain config.describe() into pipeline description."""
        config = ExtractionConfig(confidence_threshold=0.6, max_entities=50)
        generator = OntologyGenerator()
        
        # Config description standalone
        config_desc = config.describe()
        assert "threshold=0.6" in config_desc
        
        # Full pipeline description
        entities = [Entity(id="e1", type="Person", text="Test", confidence=0.8)]
        result = EntityExtractionResult(entities=entities, relationships=[], confidence=0.8)
        pipeline_desc = generator.describe_extraction_pipeline(config, result)
        
        # Both descriptions should be present
        assert config_desc.split(":")[0] in pipeline_desc  # "ExtractionConfig"

    def test_describe_stable_output(self):
        """describe() produces stable, consistent output."""
        config = ExtractionConfig(confidence_threshold=0.7)
        desc1 = config.describe()
        desc2 = config.describe()
        assert desc1 == desc2

    def test_batch_config_descriptions(self):
        """Multiple configs can be described for comparison."""
        configs = [
            ExtractionConfig(confidence_threshold=0.5),
            ExtractionConfig(confidence_threshold=0.7),
            ExtractionConfig(confidence_threshold=0.9),
        ]
        descriptions = [c.describe() for c in configs]
        
        # All different
        assert len(set(descriptions)) == 3
        
        # All include threshold
        assert all("threshold=" in d for d in descriptions)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
