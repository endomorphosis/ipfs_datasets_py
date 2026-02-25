"""Tests for language-aware extraction integration in OntologyGenerator."""

from __future__ import annotations

from dataclasses import dataclass, field

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    ExtractionConfig,
    ExtractionStrategy,
    OntologyGenerationContext,
    OntologyGenerator,
)


@dataclass
class _FakeLanguageConfig:
    stopwords: list[str] = field(default_factory=lambda: ["el", "la"])
    domain_vocab: dict[str, list[str]] = field(
        default_factory=lambda: {"legal": ["obligacion"]}
    )
    adjustment: float = -0.1

    def apply_confidence_adjustment(self, confidence: float) -> float:
        return max(0.0, min(1.0, confidence + self.adjustment))


class _FakeRouter:
    def __init__(self, language_code: str = "es", confidence: float = 0.93) -> None:
        self.language_code = language_code
        self.confidence = confidence
        self.cfg = _FakeLanguageConfig()

    def detect_language_with_confidence(self, _text: str) -> tuple[str, float]:
        return self.language_code, self.confidence

    def get_language_config(self, _language_code: str) -> _FakeLanguageConfig:
        return self.cfg


class _CountingRouter(_FakeRouter):
    def __init__(self) -> None:
        super().__init__()
        self.detect_calls = 0

    def detect_language_with_confidence(self, _text: str) -> tuple[str, float]:
        self.detect_calls += 1
        return super().detect_language_with_confidence(_text)


def test_build_language_aware_context_applies_adjustments_without_mutating_input() -> None:
    generator = OntologyGenerator(use_ipfs_accelerate=False)
    generator._get_language_router = lambda: _FakeRouter()  # type: ignore[method-assign]

    context = OntologyGenerationContext(
        data_source="unit-test",
        data_type="text",
        domain="legal",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
        config=ExtractionConfig(
            confidence_threshold=0.6,
            stopwords=["and"],
            domain_vocab={"legal": ["contract"]},
        ),
    )

    adjusted_context, meta = generator._build_language_aware_context(
        "La parte tiene una obligacion contractual.",
        context,
    )

    assert meta["language_aware"] is True
    assert meta["detected_language"] == "es"
    assert adjusted_context.extraction_config.confidence_threshold == 0.5
    assert set(adjusted_context.extraction_config.stopwords) == {"and", "el", "la"}
    assert set(adjusted_context.extraction_config.domain_vocab["legal"]) == {
        "contract",
        "obligacion",
    }
    # Verify original context config remains unchanged.
    assert context.extraction_config.confidence_threshold == 0.6
    assert context.extraction_config.stopwords == ["and"]
    assert context.extraction_config.domain_vocab == {"legal": ["contract"]}


def test_extract_entities_attaches_language_metadata() -> None:
    generator = OntologyGenerator(use_ipfs_accelerate=False)
    generator._get_language_router = lambda: _FakeRouter()  # type: ignore[method-assign]

    context = OntologyGenerationContext(
        data_source="unit-test",
        data_type="text",
        domain="general",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
    )
    result = generator.extract_entities("Alice signed a contract with Bob.", context)

    language_meta = result.metadata.get("language_metadata", {})
    assert language_meta["language_aware"] is True
    assert language_meta["detected_language"] == "es"
    assert language_meta["language_confidence"] == 0.93


def test_extract_entities_marks_router_unavailable_in_metadata() -> None:
    generator = OntologyGenerator(use_ipfs_accelerate=False)
    generator._get_language_router = lambda: None  # type: ignore[method-assign]

    context = OntologyGenerationContext(
        data_source="unit-test",
        data_type="text",
        domain="general",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
    )
    result = generator.extract_entities("Simple text for extraction.", context)
    language_meta = result.metadata.get("language_metadata", {})

    assert language_meta["language_aware"] is False
    assert language_meta["reason"] == "router_unavailable"


def test_extract_entities_marks_language_detection_failure_in_metadata() -> None:
    class _BrokenRouter:
        def detect_language_with_confidence(self, _text: str) -> tuple[str, float]:
            raise RuntimeError("detect failed")

    generator = OntologyGenerator(use_ipfs_accelerate=False)
    generator._get_language_router = lambda: _BrokenRouter()  # type: ignore[method-assign]

    context = OntologyGenerationContext(
        data_source="unit-test",
        data_type="text",
        domain="general",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
    )
    result = generator.extract_entities("Text that triggers language detection.", context)
    language_meta = result.metadata.get("language_metadata", {})

    assert language_meta["language_aware"] is False
    assert language_meta["reason"] == "detection_failed"


def test_language_detection_result_is_cached_for_repeated_text() -> None:
    generator = OntologyGenerator(use_ipfs_accelerate=False)
    router = _CountingRouter()
    generator._language_router = router

    context = OntologyGenerationContext(
        data_source="unit-test",
        data_type="text",
        domain="general",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
    )
    text = "Alice signed a contract with Bob."

    generator._build_language_aware_context(text, context)
    generator._build_language_aware_context(text, context)

    assert router.detect_calls == 1
