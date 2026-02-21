"""Batch 48 tests.

Covers:
- Hypothesis strategy for valid ExtractionConfig
- graphrag/__init__.py docstring has ASCII diagram
- graphrag/README.md has OntologyGenerationResult section
- common/README.md CriticResult docs (already present)
- performance benchmark harness exists
"""
from __future__ import annotations

import os

import pytest
from hypothesis import given, settings, HealthCheck


# ──────────────────────────────────────────────────────────────────────────────
# Hypothesis strategy for ExtractionConfig
# ──────────────────────────────────────────────────────────────────────────────

class TestExtractionConfigStrategy:
    """Property-based tests using the valid_extraction_config strategy."""

    @given(config=pytest.importorskip("tests.unit.optimizers.graphrag.strategies", reason="strategies module not found") if False else __import__("tests.unit.optimizers.graphrag.strategies", fromlist=["valid_extraction_config"]).valid_extraction_config())
    @settings(max_examples=30, deadline=5000, suppress_health_check=[HealthCheck.too_slow])
    def test_confidence_threshold_in_valid_range(self, config):
        assert 0.0 < config.confidence_threshold <= 1.0

    @given(config=__import__("tests.unit.optimizers.graphrag.strategies", fromlist=["valid_extraction_config"]).valid_extraction_config())
    @settings(max_examples=30, deadline=5000, suppress_health_check=[HealthCheck.too_slow])
    def test_max_entities_positive(self, config):
        assert config.max_entities >= 1

    @given(config=__import__("tests.unit.optimizers.graphrag.strategies", fromlist=["valid_extraction_config"]).valid_extraction_config())
    @settings(max_examples=30, deadline=5000, suppress_health_check=[HealthCheck.too_slow])
    def test_min_entity_length_positive(self, config):
        assert config.min_entity_length >= 1

    @given(config=__import__("tests.unit.optimizers.graphrag.strategies", fromlist=["valid_extraction_config"]).valid_extraction_config())
    @settings(max_examples=30, deadline=5000, suppress_health_check=[HealthCheck.too_slow])
    def test_stopwords_is_list(self, config):
        assert isinstance(config.stopwords, list)

    @given(config=__import__("tests.unit.optimizers.graphrag.strategies", fromlist=["valid_extraction_config"]).valid_extraction_config())
    @settings(max_examples=30, deadline=5000, suppress_health_check=[HealthCheck.too_slow])
    def test_allowed_entity_types_is_list(self, config):
        assert isinstance(config.allowed_entity_types, list)

    @given(config=__import__("tests.unit.optimizers.graphrag.strategies", fromlist=["valid_extraction_config"]).valid_extraction_config())
    @settings(max_examples=30, deadline=5000, suppress_health_check=[HealthCheck.too_slow])
    def test_to_dict_round_trip(self, config):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig
        d = config.to_dict()
        restored = ExtractionConfig.from_dict(d)
        assert restored.confidence_threshold == pytest.approx(config.confidence_threshold)
        assert restored.max_entities == config.max_entities
        assert restored.min_entity_length == config.min_entity_length

    @given(config=__import__("tests.unit.optimizers.graphrag.strategies", fromlist=["valid_extraction_config"]).valid_extraction_config())
    @settings(max_examples=20, deadline=5000, suppress_health_check=[HealthCheck.too_slow])
    def test_extract_entities_does_not_raise(self, config):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            OntologyGenerator,
            OntologyGenerationContext,
        )
        generator = OntologyGenerator()
        ctx = OntologyGenerationContext(
            data_source="bench",
            data_type="text",
            domain="general",
            config=config,
        )
        result = generator.extract_entities("Alice met Bob in London.", ctx)
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
        assert isinstance(result, EntityExtractionResult)


# ──────────────────────────────────────────────────────────────────────────────
# Architecture diagram in graphrag/__init__.py
# ──────────────────────────────────────────────────────────────────────────────

class TestGraphRAGInitDocstring:
    """Verify the ASCII architecture diagram was added to graphrag/__init__.py."""

    def _get_module_doc(self) -> str:
        import ipfs_datasets_py.optimizers.graphrag as graphrag_pkg
        return graphrag_pkg.__doc__ or ""

    def test_docstring_exists(self):
        doc = self._get_module_doc()
        assert len(doc) > 100

    def test_docstring_contains_architecture_header(self):
        doc = self._get_module_doc()
        assert "Architecture" in doc or "architecture" in doc

    def test_docstring_contains_generate_critique_loop(self):
        doc = self._get_module_doc()
        assert "generate" in doc.lower() or "Generate" in doc

    def test_docstring_contains_ontology_generator(self):
        doc = self._get_module_doc()
        assert "OntologyGenerator" in doc

    def test_docstring_contains_learning_adapter(self):
        doc = self._get_module_doc()
        assert "LearningAdapter" in doc or "OntologyLearningAdapter" in doc


# ──────────────────────────────────────────────────────────────────────────────
# OntologyGenerationResult in graphrag README
# ──────────────────────────────────────────────────────────────────────────────

class TestGraphRAGReadme:
    """Verify OntologyGenerationResult usage section was added to graphrag/README.md."""

    def _get_readme_path(self) -> str:
        import ipfs_datasets_py.optimizers.graphrag as graphrag_pkg
        import pathlib
        pkg_dir = pathlib.Path(graphrag_pkg.__file__).parent
        return str(pkg_dir / "README.md")

    def test_readme_exists(self):
        path = self._get_readme_path()
        assert os.path.exists(path)

    def test_readme_has_ontology_generation_result_section(self):
        path = self._get_readme_path()
        with open(path, encoding="utf-8") as fh:
            content = fh.read()
        assert "OntologyGenerationResult" in content

    def test_readme_has_field_reference_table(self):
        path = self._get_readme_path()
        with open(path, encoding="utf-8") as fh:
            content = fh.read()
        assert "entity_count" in content
        assert "relationship_count" in content

    def test_readme_has_usage_code_example(self):
        path = self._get_readme_path()
        with open(path, encoding="utf-8") as fh:
            content = fh.read()
        assert "generate_ontology_rich" in content


# ──────────────────────────────────────────────────────────────────────────────
# Performance benchmark harness exists
# ──────────────────────────────────────────────────────────────────────────────

class TestBenchmarkHarnessExists:
    """Verify the pytest-benchmark harness file was created."""

    def _get_bench_path(self) -> str:
        import pathlib
        # __file__ is tests/unit/optimizers/graphrag/test_batch48_features.py
        # Go up 4 levels: graphrag → optimizers → unit → tests, then down to performance
        repo = pathlib.Path(__file__).parent.parent.parent.parent
        return str(repo / "performance" / "optimizers" / "test_optimizer_benchmarks.py")

    def test_benchmark_file_exists(self):
        assert os.path.exists(self._get_bench_path())

    def test_benchmark_file_has_benchmark_fixtures(self):
        with open(self._get_bench_path(), encoding="utf-8") as fh:
            content = fh.read()
        assert "benchmark" in content

    def test_benchmark_file_has_extraction_test(self):
        with open(self._get_bench_path(), encoding="utf-8") as fh:
            content = fh.read()
        assert "extract_entities" in content

    def test_benchmark_file_has_critic_test(self):
        with open(self._get_bench_path(), encoding="utf-8") as fh:
            content = fh.read()
        assert "evaluate" in content.lower()
