"""Conformance checks for constructor inventory markdown drift."""

from __future__ import annotations

import re
from pathlib import Path

from ipfs_datasets_py.optimizers.common import supported_backend_config_source_aliases


def _constructor_inventory_doc_path() -> Path:
    """Resolve constructor inventory doc path from nested test location."""
    start = Path(__file__).resolve()
    for parent in start.parents:
        candidate = parent / "docs" / "optimizers" / "CONTEXT_CONFIG_CONSTRUCTOR_INVENTORY.md"
        if candidate.exists():
            return candidate
    # Keep a deterministic fallback path for assertion messaging.
    return start.parents[0] / "docs" / "optimizers" / "CONTEXT_CONFIG_CONSTRUCTOR_INVENTORY.md"


def test_constructor_inventory_doc_contains_core_constructor_entries() -> None:
    doc = _constructor_inventory_doc_path()
    assert doc.exists(), f"Missing constructor inventory doc: {doc}"

    text = doc.read_text(encoding="utf-8")
    constructor_lines = {
        match.group(1): match.group(2)
        for match in re.finditer(r"`([A-Za-z_][A-Za-z0-9_]*)\.__init__\(([^)]*)\)`", text)
    }

    # Keep these aligned with current core inventory targets.
    expected_with_params = {
        "OntologyGenerator": ("ipfs_accelerate_config", "use_ipfs_accelerate", "logger", "llm_backend"),
        "OntologyPipeline": ("domain", "use_llm", "max_rounds", "logger", "metric_sink"),
        "OntologyCritic": ("backend_config", "use_llm", "logger"),
        "LogicExtractor": ("model", "backend", "use_ipfs_accelerate"),
        "LogicTheoremOptimizer": ("config", "llm_backend", "extraction_mode", "domain", "logger"),
        "OptimizerLLMRouter": ("preferred_provider", "fallback_providers", "enable_tracking"),
    }

    for class_name, required_params in expected_with_params.items():
        assert class_name in constructor_lines, f"Missing constructor entry for {class_name}"
        line = constructor_lines[class_name]
        for param in required_params:
            assert param in line, f"Missing parameter '{param}' for {class_name} in doc inventory"

    # These are intentionally summarized with ellipsis in the doc.
    for summarized in ("OntologyMediator", "AgenticOptimizer"):
        assert f"`{summarized}.__init__(...)`" in text


def test_constructor_inventory_doc_mentions_current_adapter_helpers() -> None:
    doc = _constructor_inventory_doc_path()
    text = doc.read_text(encoding="utf-8")

    required_snippets = (
        "ensure_shared_context_metadata(...)",
        "ensure_shared_backend_config(...)",
        "backend_config_from_constructor_kwargs(...)",
        "supported_backend_config_source_aliases()",
        "OntologyPipeline` mapping (`use_llm`)",
        "OntologyCritic` mapping (`backend_config`, `use_llm`)",
        "LogicExtractor` mapping (`model`, `backend`)",
    )
    for snippet in required_snippets:
        assert snippet in text, f"Missing inventory snippet: {snippet}"


def test_constructor_inventory_doc_contains_minimum_shared_field_sets() -> None:
    doc = _constructor_inventory_doc_path()
    text = doc.read_text(encoding="utf-8")

    required_context_fields = (
        "- `domain: str`",
        "- `data_source: str | None`",
        "- `data_type: str | None`",
        "- `session_id: str | None`",
        "- `trace_id: str | None`",
        "- `metadata: dict[str, object]`",
    )
    required_backend_fields = (
        "- `provider: str`",
        "- `model: str`",
        "- `use_llm: bool`",
        "- `timeout_seconds: float`",
        "- `max_retries: int`",
        "- `circuit_failure_threshold: int`",
    )

    for field_line in required_context_fields:
        assert field_line in text, f"Missing shared context field line: {field_line}"
    for field_line in required_backend_fields:
        assert field_line in text, f"Missing shared backend field line: {field_line}"


def test_constructor_inventory_doc_alias_registry_matches_runtime_registry() -> None:
    doc = _constructor_inventory_doc_path()
    text = doc.read_text(encoding="utf-8")
    aliases = supported_backend_config_source_aliases()

    for source_name, source_aliases in aliases.items():
        assert f"`{source_name}`" in text, f"Missing source alias group in doc: {source_name}"
        for alias in source_aliases:
            assert f"`{alias}`" in text, f"Missing alias in doc for {source_name}: {alias}"
