"""API surface and config-merge regression coverage."""

from __future__ import annotations

import ipfs_datasets_py.optimizers as optimizers_pkg
from unittest.mock import Mock

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    ExtractionConfig,
    OntologyGenerationContext,
    OntologyGenerator,
)


def test_optimizer_package_exposes_version_string() -> None:
    assert hasattr(optimizers_pkg, "__version__")
    assert isinstance(optimizers_pkg.__version__, str)
    assert optimizers_pkg.__version__ != ""


def test_extraction_config_merge_uses_other_non_default_overrides() -> None:
    base = ExtractionConfig(confidence_threshold=0.8, max_entities=12, window_size=4)
    other = ExtractionConfig(confidence_threshold=0.5, max_entities=0, window_size=6)

    merged = base.merge(other)

    assert merged.confidence_threshold == 0.8
    assert merged.max_entities == 12
    assert merged.window_size == 6


def test_generator_call_is_shorthand_for_generate_ontology() -> None:
    generator = OntologyGenerator(use_ipfs_accelerate=False)
    context = OntologyGenerationContext(
        data_source="unit-test",
        data_type="text",
        domain="general",
        extraction_strategy="rule_based",
        config=ExtractionConfig(confidence_threshold=0.4),
    )
    expected = {"entities": [], "relationships": [], "domain": "general"}
    generator.generate_ontology = Mock(return_value=expected)  # type: ignore[method-assign]

    via_call = generator("Alice works at Acme.", context)

    assert isinstance(via_call, dict)
    assert via_call == expected
    generator.generate_ontology.assert_called_once_with("Alice works at Acme.", context)  # type: ignore[attr-defined]
