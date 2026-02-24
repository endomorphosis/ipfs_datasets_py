"""Tests for unified extraction context/config dataclasses."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.common.extraction_contexts import (
    AgenticExtractionConfig,
    BaseExtractionConfig,
    GraphRAGExtractionConfig,
    LogicExtractionConfig,
    ExtractionMode,
    OptimizationMethod,
)


def test_base_extraction_config_roundtrip_dict() -> None:
    cfg = BaseExtractionConfig(
        confidence_threshold=0.7,
        max_entities=120,
        max_assertions=90,
        domain="legal",
        custom_rules=[(r"\\bContract\\b", "Concept")],
        llm_fallback_threshold=0.3,
        min_entity_length=3,
        stopwords=["the", "and"],
        allowed_entity_types=["Person", "Organization"],
        max_confidence=0.95,
    )

    restored = BaseExtractionConfig.from_dict(cfg.to_dict())
    assert restored.confidence_threshold == 0.7
    assert restored.max_entities == 120
    assert restored.max_assertions == 90
    assert restored.domain == "legal"
    assert restored.custom_rules == [(r"\\bContract\\b", "Concept")]
    assert restored.stopwords == ["the", "and"]
    assert restored.allowed_entity_types == ["Person", "Organization"]
    assert restored.max_confidence == 0.95


def test_graphrag_config_roundtrip_dict() -> None:
    cfg = GraphRAGExtractionConfig(
        domain="medical",
        window_size=8,
        include_properties=False,
        domain_vocab={"Disease": ["diabetes", "hypertension"]},
    )
    restored = GraphRAGExtractionConfig.from_dict(cfg.to_dict())
    assert restored.domain == "medical"
    assert restored.window_size == 8
    assert restored.include_properties is False
    assert restored.domain_vocab["Disease"] == ["diabetes", "hypertension"]


def test_logic_config_invalid_mode_falls_back_to_auto() -> None:
    cfg = LogicExtractionConfig.from_dict(
        {"domain": "legal", "extraction_mode": "not-a-real-mode"}
    )
    assert cfg.domain == "legal"
    assert cfg.extraction_mode == ExtractionMode.AUTO


def test_logic_config_roundtrip_keeps_enum_mode() -> None:
    cfg = LogicExtractionConfig(
        domain="legal",
        extraction_mode=ExtractionMode.TDFOL,
        prover_list=["z3", "cvc5"],
        include_schema=True,
    )
    restored = LogicExtractionConfig.from_dict(cfg.to_dict())
    assert restored.extraction_mode == ExtractionMode.TDFOL
    assert restored.prover_list == ["z3", "cvc5"]
    assert restored.include_schema is True


def test_agentic_config_invalid_method_falls_back_to_test_driven() -> None:
    cfg = AgenticExtractionConfig.from_dict(
        {"optimization_method": "not-real", "validation_level": "extended"}
    )
    assert cfg.optimization_method == OptimizationMethod.TEST_DRIVEN
    assert cfg.validation_level == "extended"


def test_agentic_config_roundtrip_preserves_method_and_flags() -> None:
    cfg = AgenticExtractionConfig(
        domain="technical",
        optimization_method=OptimizationMethod.ADVERSARIAL,
        enable_validation=True,
        validation_level="full",
        enable_change_control=False,
        change_control_method="patch",
    )
    restored = AgenticExtractionConfig.from_dict(cfg.to_dict())
    assert restored.domain == "technical"
    assert restored.optimization_method == OptimizationMethod.ADVERSARIAL
    assert restored.enable_validation is True
    assert restored.enable_change_control is False
    assert restored.change_control_method == "patch"
