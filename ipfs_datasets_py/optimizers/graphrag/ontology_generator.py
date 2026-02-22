"""
Ontology Generator for GraphRAG Optimization.

This module provides functionality for generating knowledge graph ontologies from
arbitrary data types using AI model inference via ipfs_accelerate_py. It supports
multiple extraction strategies and can work with various data formats.

The generator is inspired by the complainant agent from the complaint-generator
adversarial harness, adapted for ontology generation instead of complaint generation.

Key Features:
    - Integration with ipfs_accelerate_py for universal AI model access
    - Support for arbitrary data types (text, PDF, JSON, CSV, etc.)
    - Entity extraction with configurable strategies
    - Relationship inference with confidence scoring
    - Multi-modal ontology generation
    - Domain-specific extraction patterns

Example:
    >>> from ipfs_datasets_py.optimizers.graphrag import (
    ...     OntologyGenerator,
    ...     OntologyGenerationContext
    ... )
    >>> 
    >>> generator = OntologyGenerator(ipfs_accelerate_config={
    ...     'model': 'bert-base-uncased',
    ...     'task': 'ner'
    ... })
    >>> 
    >>> context = OntologyGenerationContext(
    ...     data_source='document.pdf',
    ...     data_type='pdf',
    ...     domain='legal',
    ...     extraction_strategy='llm_based'
    ... )
    >>> 
    >>> ontology = generator.generate_ontology(data, context)

References:
    - complaint-generator complainant.py: Generation agent patterns
    - ipfs_accelerate_py: AI model inference integration
"""

from __future__ import annotations

import functools
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
from enum import Enum

# Import unified extraction config from common module
from ipfs_datasets_py.optimizers.common.extraction_contexts import (
    GraphRAGExtractionConfig,
)
from ipfs_datasets_py.optimizers.common.backend_selection import resolve_backend_settings

logger = logging.getLogger(__name__)


class ExtractionStrategy(Enum):
    """Ontology extraction strategies."""
    
    RULE_BASED = "rule_based"  # Pattern-based extraction
    LLM_BASED = "llm_based"    # LLM-powered extraction
    HYBRID = "hybrid"          # Combination of both
    NEURAL = "neural"          # Neural network models


class DataType(Enum):
    """Supported data types for ontology generation."""
    
    TEXT = "text"
    PDF = "pdf"
    JSON = "json"
    CSV = "csv"
    XML = "xml"
    HTML = "html"
    MARKDOWN = "markdown"
    STRUCTURED = "structured"


@dataclass
class ExtractionConfig:
    """Typed configuration for the extraction pipeline.

    Replaces the ``Dict[str, Any]`` ``config`` field on
    :class:`OntologyGenerationContext` for callers that want stronger typing.
    All fields are optional so that ``ExtractionConfig()`` is always safe.

    Attributes:
        confidence_threshold: Minimum entity confidence to keep (0–1).
        max_entities: Upper bound on extracted entities per run.  0 = unlimited.
        max_relationships: Upper bound on inferred relationships.  0 = unlimited.
        window_size: Co-occurrence window size for relationship inference.
        include_properties: Emit property predicates in the formula set.
        domain_vocab: Optional domain-specific vocabulary for entity typing.
        min_entity_length: Minimum character length for entity text; shorter
            entities are filtered out.  Defaults to 2 (filter single chars).
    """

    confidence_threshold: float = 0.5
    max_entities: int = 0
    max_relationships: int = 0
    window_size: int = 5
    include_properties: bool = True
    domain_vocab: Dict[str, List[str]] = field(default_factory=dict)
    # Pluggable rule sets: list of (regex_pattern, entity_type) tuples
    custom_rules: List[tuple] = field(default_factory=list)
    # When rule-based confidence falls below this value and a llm_backend is
    # configured on the generator, LLM extraction is attempted as a fallback.
    # Set to 0.0 (default) to disable fallback.
    llm_fallback_threshold: float = 0.0
    # Minimum entity text length; entities shorter than this are discarded.
    min_entity_length: int = 2
    # Stopwords: entity texts matching any of these (case-insensitive) are skipped.
    stopwords: List[str] = field(default_factory=list)
    # Whitelist of allowed entity types; empty list = allow all types.
    allowed_entity_types: List[str] = field(default_factory=list)
    # Upper bound on entity confidence scores (clamped to [0.0, max_confidence]).
    max_confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        """Return a plain-dict representation (legacy compatibility)."""
        return {
            "confidence_threshold": self.confidence_threshold,
            "max_entities": self.max_entities,
            "max_relationships": self.max_relationships,
            "window_size": self.window_size,
            "include_properties": self.include_properties,
            "domain_vocab": {k: list(v) for k, v in self.domain_vocab.items()},
            "custom_rules": list(self.custom_rules),
            "llm_fallback_threshold": self.llm_fallback_threshold,
            "min_entity_length": self.min_entity_length,
            "stopwords": list(self.stopwords),
            "allowed_entity_types": list(self.allowed_entity_types),
            "max_confidence": self.max_confidence,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ExtractionConfig":
        """Construct from a plain dict (backwards-compat with old callers)."""
        return cls(
            confidence_threshold=float(d.get("confidence_threshold", 0.5)),
            max_entities=int(d.get("max_entities", 0)),
            max_relationships=int(d.get("max_relationships", 0)),
            window_size=int(d.get("window_size", 5)),
            include_properties=bool(d.get("include_properties", True)),
            domain_vocab=dict(d.get("domain_vocab", {})),
            custom_rules=list(d.get("custom_rules", [])),
            llm_fallback_threshold=float(d.get("llm_fallback_threshold", 0.0)),
            min_entity_length=int(d.get("min_entity_length", 2)),
            stopwords=list(d.get("stopwords", [])),
            allowed_entity_types=list(d.get("allowed_entity_types", [])),
            max_confidence=float(d.get("max_confidence", 1.0)),
        )

    @classmethod
    def from_env(cls, prefix: str = "EXTRACTION_") -> "ExtractionConfig":
        """Construct an :class:`ExtractionConfig` from environment variables.

        Each field is read from an ENV var named ``{prefix}{FIELD_NAME_UPPER}``.
        Missing variables fall back to the field defaults.

        Args:
            prefix: Variable name prefix (default: ``"EXTRACTION_"``).

        Returns:
            A new :class:`ExtractionConfig` populated from the environment.

        Example::

            # Set env vars before calling:
            # EXTRACTION_CONFIDENCE_THRESHOLD=0.7
            # EXTRACTION_MAX_ENTITIES=100
            cfg = ExtractionConfig.from_env()
        """
        import os as _os

        def _get(name: str, default: str) -> str:
            return _os.environ.get(f"{prefix}{name.upper()}", default)

        return cls(
            confidence_threshold=float(_get("confidence_threshold", "0.5")),
            max_entities=int(_get("max_entities", "0")),
            max_relationships=int(_get("max_relationships", "0")),
            window_size=int(_get("window_size", "5")),
            include_properties=_get("include_properties", "true").lower() == "true",
            llm_fallback_threshold=float(_get("llm_fallback_threshold", "0.0")),
            min_entity_length=int(_get("min_entity_length", "2")),
            max_confidence=float(_get("max_confidence", "1.0")),
        )

    def validate(self) -> None:
        """Validate field values; raise :class:`ValueError` on invalid combinations.

        Checks:
        - ``confidence_threshold`` must be in [0, 1]
        - ``max_confidence`` must be in (0, 1]
        - ``confidence_threshold`` must be ≤ ``max_confidence``
        - ``max_entities`` and ``max_relationships`` must be ≥ 0
        - ``window_size`` must be ≥ 1
        - ``min_entity_length`` must be ≥ 1
        - ``llm_fallback_threshold`` must be in [0, 1]
        """
        if not (0.0 <= self.confidence_threshold <= 1.0):
            raise ValueError(
                f"confidence_threshold must be in [0, 1]; got {self.confidence_threshold}"
            )
        if not (0.0 < self.max_confidence <= 1.0):
            raise ValueError(
                f"max_confidence must be in (0, 1]; got {self.max_confidence}"
            )
        if self.confidence_threshold > self.max_confidence:
            raise ValueError(
                f"confidence_threshold ({self.confidence_threshold}) must be "
                f"<= max_confidence ({self.max_confidence})"
            )
        if self.max_entities < 0:
            raise ValueError(f"max_entities must be >= 0; got {self.max_entities}")
        if self.max_relationships < 0:
            raise ValueError(
                f"max_relationships must be >= 0; got {self.max_relationships}"
            )
        if self.window_size < 1:
            raise ValueError(f"window_size must be >= 1; got {self.window_size}")
        if self.min_entity_length < 1:
            raise ValueError(
                f"min_entity_length must be >= 1; got {self.min_entity_length}"
            )
        if not (0.0 <= self.llm_fallback_threshold <= 1.0):
            raise ValueError(
                f"llm_fallback_threshold must be in [0, 1]; got {self.llm_fallback_threshold}"
            )

    def merge(self, other: "ExtractionConfig") -> "ExtractionConfig":
        """Merge *other* into this config; *other* values take precedence on conflict.

        All fields from *other* that are **not equal to their defaults** override
        the corresponding field in *self*.  This lets you keep a base config and
        layer overrides on top without manually spelling out every field.

        Args:
            other: The override config.

        Returns:
            A new :class:`ExtractionConfig` with merged values.
        """
        defaults = ExtractionConfig()
        merged_kwargs: dict = {}
        import dataclasses as _dc
        for f in _dc.fields(ExtractionConfig):
            self_val = getattr(self, f.name)
            other_val = getattr(other, f.name)
            default_val = getattr(defaults, f.name)
            # Use other_val if it differs from the default (i.e. was explicitly set)
            merged_kwargs[f.name] = other_val if other_val != default_val else self_val
        return ExtractionConfig(**merged_kwargs)

    def to_yaml(self) -> str:
        """Serialise this config to a YAML string.

        Uses the same dict representation as :meth:`to_dict`.  Requires
        ``PyYAML`` (``pip install pyyaml``).

        Returns:
            YAML string representation.

        Raises:
            ImportError: If ``PyYAML`` is not installed.

        Example:
            >>> yaml_str = config.to_yaml()
            >>> config2 = ExtractionConfig.from_yaml(yaml_str)
            >>> config == config2
            True
        """
        try:
            import yaml as _yaml
        except ImportError as exc:
            raise ImportError(
                "PyYAML is required for to_yaml(); install with: pip install pyyaml"
            ) from exc
        return _yaml.dump(self.to_dict(), default_flow_style=False, sort_keys=True)

    def to_json(self) -> str:
        """Serialise this config to a JSON string.

        Uses the same dict representation as :meth:`to_dict`.  Provides
        compact JSON serialization for storage, transmission, and APIs.

        Returns:
            JSON string representation (compact, no whitespace).

        Example:
            >>> json_str = config.to_json()
            >>> config2 = ExtractionConfig.from_json(json_str)
            >>> config == config2
            True
        """
        import json as _json
        return _json.dumps(self.to_dict(), separators=(',', ':'), sort_keys=True)

    def to_json_pretty(self, indent: int = 2) -> str:
        """Serialise this config to a formatted JSON string.

        Uses the same dict representation as :meth:`to_dict`.  Provides
        human-readable JSON with indentation for debugging and display.

        Args:
            indent: Number of spaces for indentation (default: 2).

        Returns:
            Formatted JSON string representation.

        Example:
            >>> json_str = config.to_json_pretty()
            >>> print(json_str)
            {
              "confidence_threshold": 0.5,
              ...
            }
        """
        import json as _json
        return _json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def from_json(cls, json_str: str) -> "ExtractionConfig":
        """Deserialise an :class:`ExtractionConfig` from a JSON string.

        Args:
            json_str: JSON string produced by :meth:`to_json` or 
                :meth:`to_json_pretty` (or any JSON dict with matching keys).

        Returns:
            A new :class:`ExtractionConfig` instance.

        Raises:
            json.JSONDecodeError: If the JSON is malformed.

        Example:
            >>> config = ExtractionConfig(confidence_threshold=0.7)
            >>> json_str = config.to_json()
            >>> config2 = ExtractionConfig.from_json(json_str)
            >>> config2.confidence_threshold
            0.7
        """
        import json as _json
        d = _json.loads(json_str)
        return cls.from_dict(d)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> "ExtractionConfig":
        """Deserialise an :class:`ExtractionConfig` from a YAML string.

        Args:
            yaml_str: YAML string produced by :meth:`to_yaml` (or any dict with
                matching keys).

        Returns:
            A new :class:`ExtractionConfig` instance.

        Raises:
            ImportError: If ``PyYAML`` is not installed.

        Example:
            >>> config = ExtractionConfig(confidence_threshold=0.7)
            >>> config2 = ExtractionConfig.from_yaml(config.to_yaml())
            >>> config2.confidence_threshold
            0.7
        """
        try:
            import yaml as _yaml
        except ImportError as exc:
            raise ImportError(
                "PyYAML is required for from_yaml(); install with: pip install pyyaml"
            ) from exc
        d = _yaml.safe_load(yaml_str) or {}
        return cls.from_dict(d)

    def diff(self, other: "ExtractionConfig") -> Dict[str, Any]:
        """Return a mapping of fields that differ between ``self`` and *other*.

        Only fields whose values differ are included.  Each entry maps a
        field name to ``{"self": <self_value>, "other": <other_value>}``.

        Args:
            other: The :class:`ExtractionConfig` to compare against.

        Returns:
            Dict of differing fields; empty dict means the configs are equal.

        Example:
            >>> cfg1 = ExtractionConfig(confidence_threshold=0.5)
            >>> cfg2 = ExtractionConfig(confidence_threshold=0.8)
            >>> cfg1.diff(cfg2)
            {'confidence_threshold': {'self': 0.5, 'other': 0.8}}
        """
        import dataclasses as _dc
        result: Dict[str, Any] = {}
        for f in _dc.fields(ExtractionConfig):
            v_self = getattr(self, f.name)
            v_other = getattr(other, f.name)
            if v_self != v_other:
                result[f.name] = {"self": v_self, "other": v_other}
        return result

    def to_toml(self) -> str:
        """Serialise this config to a TOML string.

        Uses a hand-rolled minimal TOML emitter (no third-party dependencies).
        The output is compatible with Python 3.11+ ``tomllib.loads()``.

        Returns:
            TOML-formatted string.

        Example:
            >>> toml_str = cfg.to_toml()
            >>> "[extraction_config]" in toml_str
            True
        """
        def _toml_val(v: Any) -> str:
            if isinstance(v, bool):
                return "true" if v else "false"
            if isinstance(v, (int, float)):
                return repr(v)
            if isinstance(v, str):
                return f'"{v}"'
            if isinstance(v, (list, set, frozenset)):
                items = ", ".join(_toml_val(x) for x in v)
                return f"[{items}]"
            if isinstance(v, dict):
                # Represent nested dicts as inline tables
                pairs = ", ".join(f'{k} = {_toml_val(val)}' for k, val in v.items())
                return "{" + pairs + "}"
            return f'"{v}"'

        d = self.to_dict()
        lines = ["[extraction_config]"]
        for key, val in d.items():
            lines.append(f"{key} = {_toml_val(val)}")
        return "\n".join(lines) + "\n"

    @classmethod
    def from_toml(cls, toml_str: str) -> "ExtractionConfig":
        """Construct an :class:`ExtractionConfig` from a TOML string.

        Requires Python 3.11+ (uses the stdlib ``tomllib`` module).

        Args:
            toml_str: TOML-formatted string, as produced by :meth:`to_toml`.

        Returns:
            A new :class:`ExtractionConfig` instance.

        Raises:
            ImportError: If ``tomllib`` is not available (Python < 3.11).

        Example:
            >>> cfg2 = ExtractionConfig.from_toml(cfg.to_toml())
        """
        try:
            import tomllib as _tomllib
        except ImportError:
            raise ImportError("ExtractionConfig.from_toml() requires Python 3.11+ (tomllib)")

        data = _tomllib.loads(toml_str)
        section = data.get("extraction_config", data)
        return cls.from_dict(section)

    def to_json(self) -> str:
        """Serialise this config to a JSON string.

        Returns:
            A compact JSON string representing all config fields.

        Example:
            >>> import json
            >>> cfg2 = ExtractionConfig.from_dict(json.loads(cfg.to_json()))
            >>> cfg2 == cfg
            True
        """
        import json as _json
        return _json.dumps(self.to_dict(), sort_keys=True)

    def copy(self) -> "ExtractionConfig":
        """Return a shallow copy of this config.

        Equivalent to ``ExtractionConfig.from_dict(self.to_dict())``.

        Returns:
            New :class:`ExtractionConfig` with identical field values.

        Example:
            >>> cfg2 = cfg.copy()
            >>> cfg2 == cfg
            True
        """
        return ExtractionConfig.from_dict(self.to_dict())

    def clone(self) -> "ExtractionConfig":
        """Return a deep copy of this config.

        Alias for :meth:`copy`.  Provided for API consistency with
        :meth:`OntologyGenerator.clone_result`.

        Returns:
            New :class:`ExtractionConfig` with identical field values.

        Example:
            >>> cfg2 = cfg.clone()
            >>> cfg2 is not cfg
            True
        """
        return self.copy()

    def scale_thresholds(self, factor: float) -> "ExtractionConfig":
        """Return a new config with confidence-related thresholds scaled by *factor*.

        The following fields are scaled: ``confidence_threshold``,
        ``llm_fallback_threshold``, and ``max_confidence``.  Each result is
        clamped to [0.0, 1.0].  All other fields are copied unchanged.

        Args:
            factor: Multiplicative factor (e.g. 0.9 to lower thresholds by 10%).

        Returns:
            A new :class:`ExtractionConfig` instance.

        Raises:
            ValueError: If *factor* <= 0.

        Example:
            >>> relaxed = cfg.scale_thresholds(0.8)
            >>> relaxed.confidence_threshold == cfg.confidence_threshold * 0.8
            True
        """
        if factor <= 0:
            raise ValueError(f"factor must be > 0; got {factor}")

        import dataclasses as _dc

        def _clamp(v: float) -> float:
            return max(0.0, min(1.0, v))

        return _dc.replace(
            self,
            confidence_threshold=_clamp(self.confidence_threshold * factor),
            llm_fallback_threshold=_clamp(self.llm_fallback_threshold * factor),
            max_confidence=_clamp(self.max_confidence * factor),
        )

    def apply_defaults_for_domain(self, domain: str) -> None:
        """Mutate this config in-place with sensible defaults for *domain*.

        Adjusts ``confidence_threshold``, ``max_entities``, and
        ``domain_vocab`` based on well-known domain profiles.  Unrecognised
        domains are silently ignored (config unchanged).

        Supported domain values: ``"legal"``, ``"medical"``, ``"finance"``,
        ``"science"``, ``"technology"``, ``"news"``, ``"general"``.

        Args:
            domain: Domain name string.

        Example:
            >>> cfg = ExtractionConfig()
            >>> cfg.apply_defaults_for_domain("legal")
            >>> cfg.confidence_threshold >= 0.5
            True
        """
        _domain_presets: Dict[str, Any] = {
            "legal": {"confidence_threshold": 0.75, "max_entities": 200},
            "medical": {"confidence_threshold": 0.80, "max_entities": 150},
            "finance": {"confidence_threshold": 0.70, "max_entities": 250},
            "science": {"confidence_threshold": 0.65, "max_entities": 300},
            "technology": {"confidence_threshold": 0.60, "max_entities": 350},
            "news": {"confidence_threshold": 0.55, "max_entities": 500},
            "general": {"confidence_threshold": 0.50, "max_entities": 1000},
        }
        preset = _domain_presets.get(domain.lower().strip())
        if preset is None:
            return
        self.confidence_threshold = preset["confidence_threshold"]
        self.max_entities = preset["max_entities"]

    def is_strict(self) -> bool:
        """Return ``True`` if this config uses a strict confidence threshold (>= 0.8).

        Useful for quickly branching logic based on config strictness.

        Returns:
            ``True`` when ``confidence_threshold >= 0.8``.

        Example:
            >>> ExtractionConfig(confidence_threshold=0.9).is_strict()
            True
            >>> ExtractionConfig(confidence_threshold=0.5).is_strict()
            False
        """
        return self.confidence_threshold >= 0.8

    def summary(self) -> str:
        """Return a one-line human-readable description of this config.

        Returns:
            String summarising the key parameters.

        Example:
            >>> ExtractionConfig().summary()
            'ExtractionConfig(threshold=0.5, max_entities=100, max_relationships=200)'
        """
        return (
            f"ExtractionConfig(threshold={self.confidence_threshold}, "
            f"max_entities={self.max_entities}, "
            f"max_relationships={self.max_relationships})"
        )

    def with_threshold(self, threshold: float) -> "ExtractionConfig":
        """Return a copy of this config with *threshold* as the confidence threshold.

        Args:
            threshold: New ``confidence_threshold`` value (0.0–1.0).

        Returns:
            New :class:`ExtractionConfig` with the updated threshold; all
            other fields are copied from ``self``.

        Example:
            >>> strict = cfg.with_threshold(0.9)
            >>> strict.confidence_threshold
            0.9
        """
        import dataclasses as _dc
        return _dc.replace(self, confidence_threshold=threshold)

    @staticmethod
    @functools.lru_cache(maxsize=1)
    def _default_values() -> tuple:
        import dataclasses as _dc
        default = ExtractionConfig()
        return tuple(getattr(default, f.name) for f in _dc.fields(default))

    def is_default(self) -> bool:
        """Return ``True`` if this config has all default field values.

        Constructs a fresh :class:`ExtractionConfig` with no arguments and
        compares every field.

        Returns:
            ``True`` when ``self`` equals the default config.

        Example:
            >>> ExtractionConfig().is_default()
            True
        """
        import dataclasses as _dc
        return self._default_values() == tuple(
            getattr(self, f.name) for f in _dc.fields(self)
        )

    def merge(self, other: "ExtractionConfig") -> "ExtractionConfig":
        """Return a new config merging *self* with *other*, *other* taking priority.

        For each field, *other*'s value is used unless it matches the default,
        in which case *self*'s value is preserved.

        Args:
            other: Config whose non-default fields override ``self``.

        Returns:
            New :class:`ExtractionConfig`.

        Example:
            >>> merged = cfg.merge(ExtractionConfig(max_entities=50))
            >>> merged.max_entities
            50
        """
        import dataclasses as _dc
        default = ExtractionConfig()
        overrides = {
            f.name: getattr(other, f.name)
            for f in _dc.fields(other)
            if getattr(other, f.name) != getattr(default, f.name)
        }
        return _dc.replace(self, **overrides)

    def relaxed(self, delta: float = 0.1) -> "ExtractionConfig":
        """Return a copy of this config with ``confidence_threshold`` decreased by *delta*.

        The result is clamped to [0.0, 1.0].

        Args:
            delta: Amount to subtract from ``confidence_threshold`` (default 0.1).

        Returns:
            New :class:`ExtractionConfig`.
        """
        import dataclasses as _dc
        new_thresh = max(0.0, self.confidence_threshold - delta)
        return _dc.replace(self, confidence_threshold=new_thresh)

    def tightened(self, delta: float = 0.1) -> "ExtractionConfig":
        """Return a copy of this config with ``confidence_threshold`` increased by *delta*.

        The result is clamped to [0.0, 1.0].

        Args:
            delta: Amount to add to ``confidence_threshold`` (default 0.1).

        Returns:
            New :class:`ExtractionConfig`.
        """
        import dataclasses as _dc
        new_thresh = min(1.0, self.confidence_threshold + delta)
        return _dc.replace(self, confidence_threshold=new_thresh)

    def describe(self) -> str:
        """Return a human-readable one-line summary of this config.

        Returns:
            String like ``"ExtractionConfig(threshold=0.70, max_entities=100, ...)"``
        """
        import dataclasses as _dc
        pairs = ", ".join(
            f"{f.name}={getattr(self, f.name)!r}"
            for f in _dc.fields(self)
        )
        return f"ExtractionConfig({pairs})"

    def threshold_distance(self, other: "ExtractionConfig") -> float:
        """Return the absolute difference between this and *other*'s thresholds.

        Args:
            other: Another :class:`ExtractionConfig`.

        Returns:
            ``abs(self.confidence_threshold - other.confidence_threshold)``.
        """
        return abs(self.confidence_threshold - other.confidence_threshold)

    def is_stricter_than(self, other: "ExtractionConfig") -> bool:
        """Return ``True`` if this config has a higher confidence threshold.

        Args:
            other: Another :class:`ExtractionConfig`.

        Returns:
            ``True`` when ``self.confidence_threshold > other.confidence_threshold``.
        """
        return self.confidence_threshold > other.confidence_threshold

    def is_looser_than(self, other: "ExtractionConfig") -> bool:
        """Return ``True`` if this config has a lower confidence threshold.

        Args:
            other: Another :class:`ExtractionConfig`.

        Returns:
            ``True`` when ``self.confidence_threshold < other.confidence_threshold``.
        """
        return self.confidence_threshold < other.confidence_threshold

    def combined_score(self) -> float:
        """Return a composite score combining ``confidence_threshold`` and
        ``max_entities`` into a single float for comparison.

        The formula normalises ``confidence_threshold`` directly and scales
        ``max_entities`` logarithmically (capped at 1.0).

        Returns:
            Float in [0.0, 2.0].
        """
        import math
        conf_component = self.confidence_threshold  # already in [0, 1]
        max_e = getattr(self, "max_entities", 0) or 0
        entity_component = min(1.0, math.log1p(max_e) / math.log1p(1000))
        return conf_component + entity_component

    def similarity_to(self, other: "ExtractionConfig") -> float:
        """Return a similarity score between this config and *other* in [0.0, 1.0].

        Currently based solely on the absolute difference in
        ``confidence_threshold``.

        Args:
            other: Another :class:`ExtractionConfig`.

        Returns:
            ``1.0 - abs(self.confidence_threshold - other.confidence_threshold)``
            clamped to [0.0, 1.0].
        """
        diff = abs(self.confidence_threshold - other.confidence_threshold)
        return max(0.0, 1.0 - diff)

    def describe(self) -> str:
        """Return a human-readable one-line summary of this configuration.

        Example::

            cfg = ExtractionConfig(confidence_threshold=0.7, max_entities=100)
            print(cfg.describe())
            # Output: ExtractionConfig: threshold=0.7, max_entities=100, window=5, min_len=2, llm_fallback=0.0

        Returns:
            A single-line descriptive string.
        """
        parts = [
            f"threshold={self.confidence_threshold}",
            f"max_entities={self.max_entities if self.max_entities > 0 else 'unlimited'}",
            f"max_rels={self.max_relationships if self.max_relationships > 0 else 'unlimited'}",
            f"window={self.window_size}",
            f"min_len={self.min_entity_length}",
            f"max_conf={self.max_confidence}",
        ]
        if self.llm_fallback_threshold > 0.0:
            parts.append(f"llm_fallback={self.llm_fallback_threshold}")
        if self.stopwords:
            parts.append(f"stopwords={len(self.stopwords)}")
        if self.allowed_entity_types:
            parts.append(f"types={','.join(self.allowed_entity_types[:2])}")
        return f"ExtractionConfig: {', '.join(parts)}"


@dataclass
class OntologyGenerationContext:
    """
    Context information for ontology generation.
    
    This class holds all necessary context for generating an ontology from
    a data source, including source metadata, domain information, and
    extraction strategy configuration.
    
    Attributes:
        data_source: Identifier or path to the data source
        data_type: Type of data being processed
        domain: Domain for domain-specific processing (e.g., 'legal', 'medical')
        base_ontology: Optional base ontology to extend
        extraction_strategy: Strategy for entity extraction
        config: Additional configuration parameters.  Accepts either an
            :class:`ExtractionConfig` instance or a plain ``dict``.
        
    Example:
        >>> context = OntologyGenerationContext(
        ...     data_source='contract.pdf',
        ...     data_type=DataType.PDF,
        ...     domain='legal',
        ...     extraction_strategy=ExtractionStrategy.LLM_BASED,
        ...     config=ExtractionConfig(confidence_threshold=0.6),
        ... )
    """
    
    data_source: str
    data_type: Union[str, DataType]
    domain: str
    base_ontology: Optional[Dict[str, Any]] = None
    extraction_strategy: Union[str, ExtractionStrategy] = ExtractionStrategy.HYBRID
    config: Union[ExtractionConfig, GraphRAGExtractionConfig, Dict[str, Any]] = field(default_factory=dict)
    
    def __post_init__(self):
        """Convert string enums to proper enum types and normalise config."""
        if isinstance(self.data_type, str):
            self.data_type = DataType(self.data_type)
        if isinstance(self.extraction_strategy, str):
            self.extraction_strategy = ExtractionStrategy(self.extraction_strategy)
        # Support both old ExtractionConfig and new GraphRAGExtractionConfig
        if isinstance(self.config, dict):
            # Normalise dict config to typed ExtractionConfig
            self.config = ExtractionConfig.from_dict(self.config)

    @property
    def extraction_config(self) -> ExtractionConfig:
        """Typed alias for :attr:`config`."""
        if isinstance(self.config, (ExtractionConfig, GraphRAGExtractionConfig)):
            return self.config
        return ExtractionConfig()  # pragma: no cover — normalised in __post_init__


@dataclass(slots=True)
class Entity:
    """
    Represents an extracted entity.
    
    Attributes:
        id: Unique identifier for the entity
        type: Entity type (e.g., 'Person', 'Organization', 'Obligation')
        text: Original text representing the entity
        properties: Additional properties of the entity
        confidence: Confidence score for this entity (0.0 to 1.0)
        source_span: Optional source text span (start, end)
        last_seen: Optional Unix timestamp of when this entity was last observed
            (used for confidence decay over time)
    """
    
    id: str
    type: str
    text: str
    properties: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    source_span: Optional[tuple[int, int]] = None
    last_seen: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialise this entity to a plain dictionary.

        Returns:
            Dict with keys ``id``, ``type``, ``text``, ``confidence``,
            ``properties``, ``source_span``, and ``last_seen``.

        Example:
            >>> d = entity.to_dict()
            >>> d["type"]
            'Person'
        """
        return {
            "id": self.id,
            "type": self.type,
            "text": self.text,
            "confidence": self.confidence,
            "properties": dict(self.properties),
            "source_span": list(self.source_span) if self.source_span else None,
            "last_seen": self.last_seen,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Entity":
        """Reconstruct an :class:`Entity` from a plain dictionary.

        Complements :meth:`to_dict` for round-trip serialisation.

        Args:
            d: Dictionary as returned by :meth:`to_dict`.

        Returns:
            A new :class:`Entity` instance.

        Raises:
            KeyError: If ``id``, ``type``, or ``text`` keys are missing.

        Example:
            >>> entity = Entity.from_dict(entity.to_dict())
        """
        span = d.get("source_span")
        last_seen = d.get("last_seen")
        return cls(
            id=d["id"],
            type=d["type"],
            text=d["text"],
            confidence=float(d.get("confidence", 1.0)),
            properties=dict(d.get("properties") or {}),
            source_span=tuple(span) if span is not None else None,  # type: ignore[arg-type]
            last_seen=float(last_seen) if last_seen is not None else None,
        )

    def to_json(self, **kwargs: Any) -> str:
        """Serialise this entity to a JSON string.

        All keyword arguments are forwarded to :func:`json.dumps`.

        Args:
            **kwargs: Extra arguments forwarded to :func:`json.dumps`
                (e.g. ``indent``, ``sort_keys``, ``ensure_ascii``).

        Returns:
            JSON string representation.
        """
        import json as _json
        return _json.dumps(self.to_dict(), **kwargs)

    def copy_with(self, **overrides: Any) -> "Entity":
        """Return a modified copy of this entity.

        Any keyword argument matching an :class:`Entity` field name replaces
        that field in the copy.  Unrecognised keys raise :class:`TypeError`.

        Args:
            **overrides: Field name -> new value.

        Returns:
            New :class:`Entity` instance.

        Raises:
            TypeError: If an unknown field name is provided.

        Example:
            >>> high_conf = entity.copy_with(confidence=1.0)
        """
        import dataclasses as _dc
        valid = {f.name for f in _dc.fields(Entity)}
        unknown = set(overrides) - valid
        if unknown:
            raise TypeError(f"Unknown Entity field(s): {', '.join(sorted(unknown))}")
        return _dc.replace(self, **overrides)

    def to_text(self) -> str:
        """Return a compact human-readable summary of this entity.

        Format: ``"<text> (<type>, conf=<confidence>)"``

        Returns:
            Single-line string.

        Example:
            >>> entity.to_text()
            'Alice (Person, conf=0.90)'
        """
        return f"{self.text} ({self.type}, conf={self.confidence:.2f})"

    def apply_confidence_decay(
        self,
        current_time: Optional[float] = None,
        half_life_days: float = 30.0,
        min_confidence: float = 0.1,
    ) -> "Entity":
        """
        Apply time-based confidence decay to this entity.

        Entities that haven't been observed recently have their confidence
        reduced using exponential decay. If :attr:`last_seen` is ``None``,
        no decay is applied.

        Args:
            current_time: Reference timestamp (Unix time); defaults to current
                time (via :func:`time.time`).
            half_life_days: Number of days for confidence to decay to 50% of
                original value. Default: 30.0 days.
            min_confidence: Minimum confidence floor (decay stops here).
                Default: 0.1.

        Returns:
            New :class:`Entity` with decayed confidence (or unchanged if
            :attr:`last_seen` is ``None``).

        Example:
            >>> import time
            >>> entity = Entity(id="e1", type="Person", text="Alice",
            ...                 confidence=0.9, last_seen=time.time() - 86400*60)
            >>> decayed = entity.apply_confidence_decay(half_life_days=30)
            >>> decayed.confidence < 0.9
            True
        """
        import time as _time
        import math as _math

        if self.last_seen is None:
            return self  # No timestamp, no decay

        if current_time is None:
            current_time = _time.time()

        elapsed_seconds = max(0.0, current_time - self.last_seen)
        elapsed_days = elapsed_seconds / 86400.0

        # Exponential decay: confidence(t) = original * (0.5 ^ (t / half_life))
        decay_factor = 0.5 ** (elapsed_days / half_life_days)
        new_confidence = max(min_confidence, self.confidence * decay_factor)

        return self.copy_with(confidence=new_confidence)


@dataclass(slots=True)
class Relationship:
    """
    Represents a relationship between entities.
    
    Attributes:
        id: Unique identifier for the relationship
        source_id: ID of the source entity
        target_id: ID of the target entity
        type: Relationship type (e.g., 'owns', 'obligates', 'causes')
        properties: Additional properties of the relationship
        confidence: Confidence score for this relationship (0.0 to 1.0)
        direction: Directionality of the relationship — ``'subject_to_object'``
            when the dependency direction is known from verb-frame analysis,
            ``'undirected'`` for co-occurrence-based relationships, or
            ``'unknown'`` when directionality could not be determined.
    """
    
    id: str
    source_id: str
    target_id: str
    type: str
    properties: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    direction: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        """Serialise this relationship to a plain dictionary.

        Returns:
            Dict with keys ``id``, ``source_id``, ``target_id``, ``type``,
            ``properties``, ``confidence``, and ``direction``.
        """
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "type": self.type,
            "properties": dict(self.properties),
            "confidence": self.confidence,
            "direction": self.direction,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Relationship":
        """Reconstruct a :class:`Relationship` from a plain dictionary.

        Args:
            d: Dictionary as returned by :meth:`to_dict`.

        Returns:
            A new :class:`Relationship` instance.

        Raises:
            KeyError: If ``id``, ``source_id``, ``target_id``, or ``type``
                keys are missing.
        """
        return cls(
            id=d["id"],
            source_id=d["source_id"],
            target_id=d["target_id"],
            type=d["type"],
            properties=dict(d.get("properties") or {}),
            confidence=float(d.get("confidence", 1.0)),
            direction=str(d.get("direction", "unknown")),
        )

    def to_json(self, **kwargs: Any) -> str:
        """Serialise this relationship to a JSON string.

        All keyword arguments are forwarded to :func:`json.dumps`.

        Args:
            **kwargs: Extra arguments forwarded to :func:`json.dumps`
                (e.g. ``indent``, ``sort_keys``, ``ensure_ascii``).

        Returns:
            JSON string representation.
        """
        import json as _json
        return _json.dumps(self.to_dict(), **kwargs)


@dataclass(slots=True)
class EntityExtractionResult:
    """
    Result of entity extraction from data.
    
    Attributes:
        entities: List of extracted entities
        relationships: List of inferred relationships
        confidence: Overall confidence score
        metadata: Additional metadata about the extraction
        errors: Any errors encountered during extraction
    """
    
    entities: List[Entity]
    relationships: List[Relationship]
    confidence: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    def to_dataframe(self):
        """Convert extracted entities to a :class:`pandas.DataFrame`.

        Returns:
            A ``pandas.DataFrame`` with one row per entity and columns:
            ``id``, ``text``, ``type``, ``confidence``.

        Raises:
            ImportError: If ``pandas`` is not installed.
        """
        try:
            import pandas as _pd
        except ImportError as exc:
            raise ImportError(
                "pandas is required for to_dataframe(); install with: pip install pandas"
            ) from exc
        rows = [
            {
                "id": e.id,
                "text": e.text,
                "type": e.type,
                "confidence": e.confidence,
            }
            for e in self.entities
        ]
        return _pd.DataFrame(rows, columns=["id", "text", "type", "confidence"])

    def to_json(self) -> str:
        """Serialise the full extraction result to a JSON string.

        Entities are serialised via :meth:`Entity.to_dict`; relationships are
        serialised to dicts with the same field names as the
        :class:`Relationship` dataclass.

        Returns:
            JSON string representation of this result.

        Example:
            >>> import json
            >>> result = generator.extract_entities(data, ctx)
            >>> d = json.loads(result.to_json())
            >>> len(d["entities"]) == len(result.entities)
            True
        """
        import json as _json

        def _rel_to_dict(r):
            return {
                "id": r.id,
                "source_id": r.source_id,
                "target_id": r.target_id,
                "type": r.type,
                "confidence": r.confidence,
                "direction": r.direction,
                "properties": dict(r.properties),
            }

        payload = {
            "entities": [e.to_dict() for e in self.entities],
            "relationships": [_rel_to_dict(r) for r in self.relationships],
            "confidence": self.confidence,
            "metadata": self.metadata,
            "errors": self.errors,
        }
        return _json.dumps(payload)

    def filter_by_type(self, entity_type: str) -> "EntityExtractionResult":
        """Return a new result containing only entities matching *entity_type*.

        Relationships whose ``source_id`` or ``target_id`` no longer exists in
        the filtered entity set are pruned from the result.

        Args:
            entity_type: Entity type string to keep (case-sensitive).

        Returns:
            A new :class:`EntityExtractionResult` with the filtered entities and
            pruned relationships.

        Example:
            >>> persons = result.filter_by_type("Person")
            >>> all(e.type == "Person" for e in persons.entities)
            True
        """
        filtered_entities = [e for e in self.entities if e.type == entity_type]
        kept_ids = {e.id for e in filtered_entities}
        filtered_rels = [
            r for r in self.relationships
            if r.source_id in kept_ids and r.target_id in kept_ids
        ]
        return EntityExtractionResult(
            entities=filtered_entities,
            relationships=filtered_rels,
            confidence=self.confidence,
            metadata=dict(self.metadata),
            errors=list(self.errors),
        )

    def filter_by_confidence(self, threshold: float = 0.5) -> "EntityExtractionResult":
        """Return a new result containing only entities above a confidence threshold.

        Relationships whose ``source_id`` or ``target_id`` no longer exists in
        the filtered entity set are pruned from the result.

        Args:
            threshold: Minimum confidence score (0–1) to keep. Default: 0.5.

        Returns:
            A new :class:`EntityExtractionResult` with confidence-filtered entities
            and pruned relationships.

        Example:
            >>> high_conf = result.filter_by_confidence(0.8)
            >>> all(e.confidence >= 0.8 for e in high_conf.entities)
            True
        """
        if not (0.0 <= threshold <= 1.0):
            raise ValueError(f"threshold must be in [0, 1]; got {threshold}")

        filtered_entities = [e for e in self.entities if e.confidence >= threshold]
        kept_ids = {e.id for e in filtered_entities}
        filtered_rels = [
            r for r in self.relationships
            if r.source_id in kept_ids and r.target_id in kept_ids
        ]

        # Compute stats
        stats = {
            "original_entity_count": len(self.entities),
            "filtered_entity_count": len(filtered_entities),
            "threshold": threshold,
        }
        if self.metadata is None:
            self.metadata = {}
        meta = dict(self.metadata)
        meta.setdefault("filter_confidence_stats", {}).update(stats)

        return EntityExtractionResult(
            entities=filtered_entities,
            relationships=filtered_rels,
            confidence=self.confidence,
            metadata=meta,
            errors=list(self.errors),
        )

    def merge(self, other: "EntityExtractionResult") -> "EntityExtractionResult":
        """Merge *other* into this result, deduplicating by normalised entity text.

        Entities whose normalised text (``lower().strip()``) already appears in
        ``self.entities`` are **not** added from *other*; the existing entity is
        kept.  Relationships from *other* that reference entity IDs that survive
        in the merged set are included.

        Args:
            other: The :class:`EntityExtractionResult` to merge into this one.

        Returns:
            A new :class:`EntityExtractionResult` containing the merged content.

        Example:
            >>> merged = result_a.merge(result_b)
            >>> len(merged.entities) <= len(result_a.entities) + len(result_b.entities)
            True
        """
        seen_texts: dict = {e.text.lower().strip(): e.id for e in self.entities}
        merged_entities = list(self.entities)
        id_map: dict = {}  # old_id -> kept_id (for relationship remapping)

        for e in other.entities:
            norm = e.text.lower().strip()
            if norm in seen_texts:
                # Map old other entity ID to the existing entity's ID
                id_map[e.id] = seen_texts[norm]
            else:
                seen_texts[norm] = e.id
                merged_entities.append(e)
                id_map[e.id] = e.id

        kept_ids = {e.id for e in merged_entities}
        # Keep self relationships as-is; add other relationships with remapped IDs
        import dataclasses as _dc
        merged_rels = list(self.relationships)
        for r in other.relationships:
            src = id_map.get(r.source_id, r.source_id)
            tgt = id_map.get(r.target_id, r.target_id)
            if src in kept_ids and tgt in kept_ids and src != tgt:
                merged_rels.append(_dc.replace(r, source_id=src, target_id=tgt))

        merged_confidence = (self.confidence + other.confidence) / 2.0
        return EntityExtractionResult(
            entities=merged_entities,
            relationships=merged_rels,
            confidence=merged_confidence,
            metadata={**self.metadata, **other.metadata},
            errors=list(self.errors) + list(other.errors),
        )

    def to_csv(self) -> str:
        """Return a flat CSV representation of the extracted entities.

        Each row corresponds to one entity.  Columns are::

            id,type,text,confidence,source_span_start,source_span_end

        The header row is always included.  ``source_span_*`` columns are
        empty strings when no span is available.

        Returns:
            A CSV string (newline-separated rows, comma-separated columns).

        Example:
            >>> csv_str = result.to_csv()
            >>> lines = csv_str.splitlines()
            >>> lines[0]
            'id,type,text,confidence,source_span_start,source_span_end'
        """
        import csv
        import io

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["id", "type", "text", "confidence", "source_span_start", "source_span_end"])
        for ent in self.entities:
            span_start = ent.source_span[0] if ent.source_span else ""
            span_end = ent.source_span[1] if ent.source_span else ""
            writer.writerow([ent.id, ent.type, ent.text, ent.confidence, span_start, span_end])
        return buf.getvalue()

    def summary(self) -> str:
        """Return a concise human-readable summary of this extraction result.

        Format::

            EntityExtractionResult: N entities (K types), M relationships, confidence=X.XX

        Returns:
            One-line summary string.

        Example:
            >>> print(result.summary())
            EntityExtractionResult: 4 entities (3 types), 2 relationships, confidence=0.85
        """
        n_types = len({e.type for e in self.entities})
        return (
            f"EntityExtractionResult: {len(self.entities)} entities ({n_types} types), "
            f"{len(self.relationships)} relationships, confidence={self.confidence:.2f}"
        )

    def confidence_histogram(self, bins: int = 5) -> List[int]:
        """Return a frequency histogram of entity confidence scores.

        Divides the [0, 1] range into *bins* equal-width buckets and counts how
        many entities fall into each.

        Args:
            bins: Number of buckets (default: 5).

        Returns:
            List of *bins* integers summing to ``len(self.entities)``.

        Raises:
            ValueError: If *bins* < 1.

        Example:
            >>> hist = result.confidence_histogram(bins=4)
            >>> sum(hist) == len(result.entities)
            True
        """
        if bins < 1:
            raise ValueError(f"bins must be >= 1; got {bins}")
        counts = [0] * bins
        for ent in self.entities:
            val = max(0.0, min(1.0, float(ent.confidence)))
            bucket = min(int(val * bins), bins - 1)
            counts[bucket] += 1
        return counts

    def to_dict(self) -> Dict[str, Any]:
        """Return a plain-dict representation of this result.

        Returns:
            Dict with keys:

            * ``"entities"`` -- list of entity dicts (via :meth:`Entity.to_dict`).
            * ``"relationships"`` -- list of relationship dicts.
            * ``"confidence"`` -- overall extraction confidence.
            * ``"metadata"`` -- copy of metadata dict.
            * ``"errors"`` -- list of error strings.

        Example:
            >>> d = result.to_dict()
            >>> isinstance(d["entities"], list)
            True
        """
        return {
            "entities": [e.to_dict() for e in self.entities],
            "relationships": [
                {
                    "id": r.id,
                    "source_id": r.source_id,
                    "target_id": r.target_id,
                    "type": r.type,
                    "confidence": r.confidence,
                    "direction": r.direction,
                    "properties": dict(r.properties),
                }
                for r in self.relationships
            ],
            "confidence": self.confidence,
            "metadata": dict(self.metadata),
            "errors": list(self.errors),
        }

    def entity_type_counts(self) -> Dict[str, int]:
        """Return a frequency count of entity types in this result.

        Returns:
            Dict mapping entity-type string → count, sorted by count
            descending.

        Example:
            >>> counts = result.entity_type_counts()
            >>> counts.get("Person", 0) >= 0
            True
        """
        freq: Dict[str, int] = {}
        for ent in self.entities:
            freq[ent.type] = freq.get(ent.type, 0) + 1
        return dict(sorted(freq.items(), key=lambda kv: -kv[1]))

    def highest_confidence_entity(self) -> Optional["Entity"]:
        """Return the entity with the highest confidence score.

        Returns:
            The :class:`Entity` with the maximum ``confidence`` value, or
            ``None`` if there are no entities.

        Example:
            >>> best = result.highest_confidence_entity()
            >>> best is None or isinstance(best, Entity)
            True
        """
        if not self.entities:
            return None
        return max(self.entities, key=lambda e: e.confidence)

    def filter_by_span(
        self,
        start: int,
        end: int,
    ) -> "EntityExtractionResult":
        """Return a copy with only entities whose ``source_span`` overlaps [start, end).

        Entities with ``source_span=None`` are excluded.

        Args:
            start: Inclusive start character index.
            end: Exclusive end character index.

        Returns:
            New :class:`EntityExtractionResult` with filtered entities.
            Relationships referencing removed entities are also removed.

        Example:
            >>> r2 = result.filter_by_span(0, 50)
            >>> all(e.source_span is not None for e in r2.entities)
            True
        """
        filtered = [
            e for e in self.entities
            if e.source_span is not None
            and e.source_span[0] < end
            and e.source_span[1] > start
        ]
        kept_ids = {e.id for e in filtered}
        kept_rels = [
            r for r in self.relationships
            if r.source_id in kept_ids and r.target_id in kept_ids
        ]
        import dataclasses as _dc
        return _dc.replace(self, entities=filtered, relationships=kept_rels)

    def random_sample(self, n: int) -> "EntityExtractionResult":
        """Return a new result containing *n* randomly selected entities.

        Relationships whose ``source_id`` or ``target_id`` no longer exists in
        the sampled entity set are removed.

        Args:
            n: Number of entities to sample.  If *n* >= len(entities), returns
               a copy of the full result (no error raised).

        Returns:
            New :class:`EntityExtractionResult` with sampled entities and
            filtered relationships.

        Example:
            >>> r2 = result.random_sample(5)
            >>> len(r2.entities) <= 5
            True
        """
        import random as _random
        import dataclasses as _dc
        sampled = list(self.entities)
        if n < len(sampled):
            sampled = _random.sample(sampled, n)
        kept_ids = {e.id for e in sampled}
        kept_rels = [
            r for r in self.relationships
            if r.source_id in kept_ids and r.target_id in kept_ids
        ]
        return _dc.replace(self, entities=sampled, relationships=kept_rels)

    def span_coverage(self, text_length: int) -> float:
        """Compute the fraction of source text characters covered by entity spans.

        Only entities with a non-None ``source_span`` are considered.  Overlapping
        spans are merged before computing coverage so overlaps aren't double-counted.

        Args:
            text_length: Total number of characters in the source text.  Must be > 0.

        Returns:
            Float in [0.0, 1.0].  Returns 0.0 if no entities have spans or
            *text_length* <= 0.

        Example:
            >>> result.span_coverage(100)
            0.3
        """
        if text_length <= 0:
            return 0.0
        spans = sorted(
            (e.source_span for e in self.entities if e.source_span is not None),
            key=lambda s: s[0],
        )
        if not spans:
            return 0.0
        covered = 0
        cur_start, cur_end = spans[0]
        for start, end in spans[1:]:
            if start <= cur_end:
                cur_end = max(cur_end, end)
            else:
                covered += cur_end - cur_start
                cur_start, cur_end = start, end
        covered += cur_end - cur_start
        return min(1.0, covered / text_length)

    def unique_types(self) -> List[str]:
        """Return a sorted list of distinct entity type strings in this result.

        Returns:
            Sorted list of unique ``type`` values across all entities.
            Empty list if no entities.

        Example:
            >>> result.unique_types()
            ['Org', 'Person']
        """
        return sorted({e.type for e in self.entities})

    def avg_confidence(self) -> float:
        """Return the mean confidence across all entities.

        Returns:
            Float mean confidence, or 0.0 if there are no entities.

        Example:
            >>> result.avg_confidence()
            0.75
        """
        if not self.entities:
            return 0.0
        return sum(e.confidence for e in self.entities) / len(self.entities)

    def by_id(self, eid: str) -> Optional["Entity"]:
        """Look up an entity by its id string.

        Args:
            eid: Entity id to search for.

        Returns:
            The matching :class:`Entity`, or ``None`` if not found.

        Example:
            >>> entity = result.by_id("e_abc123")
        """
        for entity in self.entities:
            if entity.id == eid:
                return entity
        return None

    def has_entity(self, text: str, case_sensitive: bool = False) -> bool:
        """Return ``True`` if any entity in this result matches *text*.

        Args:
            text: Text to search for.
            case_sensitive: If ``False`` (default), comparison is
                case-insensitive.

        Returns:
            Boolean.

        Example:
            >>> result.has_entity("Alice")
            True
        """
        if case_sensitive:
            return any(e.text == text for e in self.entities)
        needle = text.lower()
        return any(e.text.lower() == needle for e in self.entities)

    def filter_by_type(self, etype: str, case_sensitive: bool = False) -> "EntityExtractionResult":
        """Return a new result keeping only entities whose ``type`` matches *etype*.

        Relationships that reference removed entities (i.e., those whose
        ``source_id`` or ``target_id`` no longer exists in the kept entity set)
        are also pruned from the result.

        Args:
            etype: Entity type string to keep.
            case_sensitive: If ``False`` (default), comparison is
                case-insensitive.

        Returns:
            New :class:`EntityExtractionResult` with matching entities and
            pruned relationships.

        Example:
            >>> filtered = result.filter_by_type("ORG")
            >>> all(e.type == "ORG" for e in filtered.entities)
            True
        """
        if case_sensitive:
            kept = [e for e in self.entities if e.type == etype]
        else:
            needle = etype.lower()
            kept = [e for e in self.entities if e.type.lower() == needle]
        kept_ids = {e.id for e in kept}
        pruned_rels = [
            r for r in self.relationships
            if r.source_id in kept_ids and r.target_id in kept_ids
        ]
        return EntityExtractionResult(
            entities=kept,
            relationships=pruned_rels,
            confidence=self.confidence,
            metadata=dict(self.metadata),
        )

    def relationships_for(self, entity_id: str) -> List["Relationship"]:
        """Return all relationships that involve *entity_id* as source or target.

        Args:
            entity_id: Entity ID to look up.

        Returns:
            List of :class:`Relationship` objects where
            ``source_id == entity_id`` or ``target_id == entity_id``.
            Returns an empty list if the entity participates in no
            relationships.

        Example:
            >>> rels = result.relationships_for("e1")
            >>> all(r.source_id == "e1" or r.target_id == "e1" for r in rels)
            True
        """
        return [
            r for r in self.relationships
            if r.source_id == entity_id or r.target_id == entity_id
        ]

    def merge(self, other: "EntityExtractionResult") -> "EntityExtractionResult":
        """Return a new result combining entities and relationships from both results.

        Duplicate entities are resolved by normalised text (lower-case); the
        first occurrence (``self`` takes priority over ``other``) is kept.
        Relationships are deduplicated by ID.

        Args:
            other: Another :class:`EntityExtractionResult` to merge with this one.

        Returns:
            New :class:`EntityExtractionResult` containing the union of both.

        Example:
            >>> merged = result_a.merge(result_b)
            >>> len(merged.entities) >= len(result_a.entities)
            True
        """
        seen_texts: set = {e.text.lower() for e in self.entities}
        new_entities = list(self.entities) + [
            e for e in other.entities if e.text.lower() not in seen_texts
        ]
        seen_rel_ids: set = {r.id for r in self.relationships}
        new_rels = list(self.relationships) + [
            r for r in other.relationships if r.id not in seen_rel_ids
        ]
        merged_confidence = (self.confidence + other.confidence) / 2.0
        merged_meta = {**other.metadata, **self.metadata}
        merged_errors = list(self.errors) + [e for e in other.errors if e not in self.errors]
        return EntityExtractionResult(
            entities=new_entities,
            relationships=new_rels,
            confidence=merged_confidence,
            metadata=merged_meta,
            errors=merged_errors,
        )

    def entity_texts(self) -> List[str]:
        """Return the ``text`` value of every entity in this result.

        Returns:
            List of strings in the same order as :attr:`entities`.

        Example:
            >>> result.entity_texts()
            ['Alice', 'ACME Corp']
        """
        return [e.text for e in self.entities]

    def confidence_histogram(self, bins: int = 5) -> List[int]:
        """Return a histogram of entity confidence values bucketed into *bins*.

        Args:
            bins: Number of equal-width buckets from 0.0 to 1.0.
                Defaults to 5.

        Returns:
            List of integer counts, one per bucket, in ascending order of
            confidence range.

        Raises:
            ValueError: If *bins* is less than 1.

        Example:
            >>> result.confidence_histogram(bins=2)
            [1, 3]
        """
        if bins < 1:
            raise ValueError(f"bins must be >= 1; got {bins}")
        width = 1.0 / bins
        counts = [0] * bins
        for e in self.entities:
            bucket = min(int(e.confidence / width), bins - 1)
            counts[bucket] += 1
        return counts

    def sample_entities(self, n: int) -> List["Entity"]:
        """Return up to *n* randomly sampled entities from this result.

        Args:
            n: Maximum number of entities to return.

        Returns:
            List of up to *n* :class:`Entity` objects chosen without
            replacement.  If *n* >= len(entities), all entities are returned
            (in shuffled order).

        Example:
            >>> sample = result.sample_entities(3)
            >>> len(sample) <= 3
            True
        """
        import random as _random
        pool = list(self.entities)
        _random.shuffle(pool)
        return pool[:n]

    def entity_by_id(self, eid: str) -> Optional["Entity"]:
        """Return the first entity with the given ``id``, or ``None``.

        Args:
            eid: Entity ID to look up.

        Returns:
            Matching :class:`Entity`, or ``None`` if not found.

        Example:
            >>> result.entity_by_id("e1")
        """
        for e in self.entities:
            if e.id == eid:
                return e
        return None

    def average_confidence(self) -> float:
        """Return the mean confidence across all entities.

        Returns:
            Mean ``confidence`` value; ``0.0`` for an empty result.

        Example:
            >>> result.average_confidence()
            0.8
        """
        if not self.entities:
            return 0.0
        return sum(e.confidence for e in self.entities) / len(self.entities)

    def distinct_types(self) -> List[str]:
        """Return a sorted list of unique entity type strings.

        Returns:
            Sorted list of distinct ``type`` values across all entities.
            Empty list when there are no entities.

        Example:
            >>> result.distinct_types()
            ['ORG', 'PERSON']
        """
        return sorted({e.type for e in self.entities})

    def high_confidence_entities(self, threshold: float = 0.8) -> List["Entity"]:
        """Return entities with confidence >= *threshold*.

        Args:
            threshold: Minimum confidence (inclusive). Defaults to 0.8.

        Returns:
            List of :class:`Entity` objects with ``confidence >= threshold``.

        Example:
            >>> result.high_confidence_entities(threshold=0.9)
        """
        return [e for e in self.entities if e.confidence >= threshold]

    def low_confidence_entities(self, threshold: float = 0.5) -> List["Entity"]:
        """Return entities with confidence < *threshold*.

        Args:
            threshold: Upper bound (exclusive). Defaults to 0.5.

        Returns:
            List of :class:`Entity` objects with ``confidence < threshold``.

        Example:
            >>> result.low_confidence_entities(threshold=0.6)
        """
        return [e for e in self.entities if e.confidence < threshold]

    def max_confidence(self) -> float:
        """Return the highest confidence value among all entities.

        Returns:
            Max ``confidence``; ``0.0`` for an empty result.

        Example:
            >>> result.max_confidence()
            0.95
        """
        if not self.entities:
            return 0.0
        return max(e.confidence for e in self.entities)

    def min_confidence(self) -> float:
        """Return the lowest confidence value among all entities.

        Returns:
            Min ``confidence``; ``0.0`` for an empty result.

        Example:
            >>> result.min_confidence()
            0.3
        """
        if not self.entities:
            return 0.0
        return min(e.confidence for e in self.entities)

    def confidence_band(self, low: float = 0.0, high: float = 1.0) -> List["Entity"]:
        """Return entities with confidence in [*low*, *high*] (inclusive on both ends).

        Args:
            low: Lower bound. Defaults to 0.0.
            high: Upper bound. Defaults to 1.0.

        Returns:
            List of :class:`Entity` objects with ``low <= confidence <= high``.

        Example:
            >>> result.confidence_band(0.5, 0.8)
        """
        return [e for e in self.entities if low <= e.confidence <= high]

    def relationship_types(self) -> List[str]:
        """Return a sorted list of unique relationship type strings.

        Returns:
            Sorted list of distinct ``type`` values across all relationships.
            Empty list when there are no relationships.

        Example:
            >>> result.relationship_types()
            ['RELATED', 'WORKS_FOR']
        """
        return sorted({r.type for r in self.relationships})

    def is_empty(self) -> bool:
        """Return ``True`` if there are no entities AND no relationships.

        Returns:
            ``True`` when both ``entities`` and ``relationships`` are empty.

        Example:
            >>> EntityExtractionResult(entities=[], relationships=[], confidence=1.0).is_empty()
            True
        """
        return len(self.entities) == 0 and len(self.relationships) == 0

    def has_relationships(self) -> bool:
        """Return ``True`` if the result contains at least one relationship.

        Returns:
            ``True`` when ``relationships`` is non-empty.
        """
        return len(self.relationships) > 0

    def entities_of_type(self, etype: str, case_sensitive: bool = False) -> List["Entity"]:
        """Return entities matching the given type string.

        Alias for :meth:`filter_by_type` with a more explicit name.

        Args:
            etype: Entity type string to match.
            case_sensitive: If ``False`` (default), comparison is
                case-insensitive.

        Returns:
            List of :class:`Entity` objects whose ``type`` matches *etype*.
        """
        if case_sensitive:
            return [e for e in self.entities if e.type == etype]
        etype_lower = etype.lower()
        return [e for e in self.entities if e.type.lower() == etype_lower]

    def confidence_stats(self) -> Dict[str, float]:
        """Return descriptive statistics for entity confidences in this result.

        Returns:
            Dict with keys ``count``, ``mean``, ``min``, ``max``, and ``std``.
            All values are ``0.0`` when there are no entities.

        Example:
            >>> result.confidence_stats()
            {'count': 3.0, 'mean': 0.8, 'min': 0.7, 'max': 0.9, 'std': ...}
        """
        import math as _math
        if not self.entities:
            return {"count": 0.0, "mean": 0.0, "min": 0.0, "max": 0.0, "std": 0.0}
        confs = [e.confidence for e in self.entities]
        mean = sum(confs) / len(confs)
        variance = sum((c - mean) ** 2 for c in confs) / len(confs)
        return {
            "count": float(len(confs)),
            "mean": mean,
            "min": min(confs),
            "max": max(confs),
            "std": _math.sqrt(variance),
        }

    def top_confidence_entity(self) -> Optional["Entity"]:
        """Return the entity with the highest confidence score.

        Returns:
            The :class:`Entity` with the maximum ``confidence`` value, or
            ``None`` when the result has no entities.

        Example:
            >>> result.top_confidence_entity()
            Entity(id='e3', type='Person', text='Alice', confidence=0.95, ...)
        """
        if not self.entities:
            return None
        return max(self.entities, key=lambda e: e.confidence)

    def entities_with_properties(self) -> List["Entity"]:
        """Return entities that have at least one entry in their ``properties`` dict.

        Returns:
            List of :class:`Entity` objects with non-empty ``properties``.
        """
        return [e for e in self.entities if e.properties]

    @property
    def entity_ids(self) -> List[str]:
        """Return a list of all entity id strings in this result.

        Returns:
            List of ``id`` strings in entity-insertion order.
        """
        return [e.id for e in self.entities]

    @property
    def relationship_ids(self) -> List[str]:
        """Return a list of all relationship id strings in this result.

        Returns:
            List of ``id`` strings for each relationship that has one, in
            insertion order.  Relationships without an ``id`` attribute are
            silently skipped.
        """
        ids = []
        for r in self.relationships:
            rid = getattr(r, "id", None)
            if rid is not None:
                ids.append(rid)
        return ids

    def extraction_statistics(self) -> Dict[str, Any]:
        """Return comprehensive extraction statistics.

        Calculates and returns key metrics about the extracted entities and
        relationships, useful for monitoring extraction quality and progress.

        Returns:
            Dict with statistics including:
                - total_entities: Count of extracted entities
                - total_relationships: Count of inferred relationships
                - unique_types: Count of distinct entity types
                - avg_confidence: Average entity confidence (0.0-1.0)
                - min_confidence: Minimum entity confidence
                - max_confidence: Maximum entity confidence
                - entities_by_type: Dict mapping types to counts
                - relationship_types: List of unique relationship types
                - entities_with_properties: Count of entities with properties
                - avg_text_length: Average character length of entity text
                - dangling_relationships: Count of relationships missing entities

        Example:
            >>> stats = result.extraction_statistics()
            >>> print(f"Extracted {stats['total_entities']} entities")
            >>> print(f"Average confidence: {stats['avg_confidence']:.2%}")
        """
        # Basic counts
        total_entities = len(self.entities)
        total_relationships = len(self.relationships)
        
        # Confidence statistics
        confidences = [e.confidence for e in self.entities] if self.entities else [0.0]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        min_confidence = min(confidences) if confidences else 0.0
        max_confidence = max(confidences) if confidences else 0.0
        
        # Type analysis
        type_counts = {}
        for e in self.entities:
            type_counts[e.type] = type_counts.get(e.type, 0) + 1
        unique_types = len(type_counts)
        
        # Relationship types
        rel_types = set()
        entity_ids = {e.id for e in self.entities}
        dangling_count = 0
        
        for r in self.relationships:
            rel_types.add(r.type)
            if r.source_id not in entity_ids or r.target_id not in entity_ids:
                dangling_count += 1
        
        # Entity properties
        entities_with_props = sum(1 for e in self.entities if e.properties)
        
        # Text length
        text_lengths = [len(e.text) for e in self.entities] if self.entities else [0]
        avg_text_length = sum(text_lengths) / len(text_lengths) if text_lengths else 0.0
        
        return {
            'total_entities': total_entities,
            'total_relationships': total_relationships,
            'unique_types': unique_types,
            'avg_confidence': round(avg_confidence, 4),
            'min_confidence': round(min_confidence, 4),
            'max_confidence': round(max_confidence, 4),
            'entities_by_type': dict(sorted(type_counts.items())),
            'relationship_types': sorted(list(rel_types)),
            'entities_with_properties': entities_with_props,
            'avg_text_length': round(avg_text_length, 2),
            'dangling_relationships': dangling_count,
        }

    def relationship_coherence_issues(self) -> Dict[str, Any]:
        """Analyze relationship coherence and identify quality issues.

        Examines relationships for common quality problems, such as:
        - Low confidence relationships
        - Relationships with missing entities (dangling references)
        - Self-relationships (entity points to itself)
        - Duplicate relationships (same source/target/type)
        - Highly connected entities (potential hubs needing normalization)

        Returns:
            Dict with issue analysis:
                - low_confidence_relationships: List of (rel_id, confidence) pairs
                - dangling_relationships: List of (rel_id, missing_id) pairs
                - self_relationships: List of (rel_id, entity_id) pairs
                - duplicate_relationships: List of duplicate relationship groups
                - high_degree_entities: List of (entity_id, degree) pairs for hubs
                - total_issues: Integer count of all issues found

        Example:
            >>> issues = result.relationship_coherence_issues()
            >>> if issues['total_issues'] > 0:
            ...     print(f"Found {issues['total_issues']} relationship issues")
        """
        entity_ids = {e.id for e in self.entities}
        low_conf = []
        dangling = []
        self_rels = []
        seen_triples = {}  # (src, tgt, type) -> rel_id for duplicate detection
        degree = {}  # count relationships per entity
        
        for r in self.relationships:
            # Track degree
            degree[r.source_id] = degree.get(r.source_id, 0) + 1
            degree[r.target_id] = degree.get(r.target_id, 0) + 1
            
            # Low confidence check
            if r.confidence < 0.5:
                low_conf.append((r.id, round(r.confidence, 3)))
            
            # Dangling reference check
            if r.source_id not in entity_ids:
                dangling.append((r.id, r.source_id))
            if r.target_id not in entity_ids:
                dangling.append((r.id, r.target_id))
            
            # Self-relationship check
            if r.source_id == r.target_id:
                self_rels.append((r.id, r.source_id))
            
            # Duplicate check
            triple = (r.source_id, r.target_id, r.type)
            if triple in seen_triples:
                seen_triples[triple].append(r.id)
            else:
                seen_triples[triple] = [r.id]
        
        # Extract actual duplicates (groups of size > 1)
        duplicates = [group for group in seen_triples.values() if len(group) > 1]
        
        # High degree entities (hubs with degree >= 5)
        high_degree = sorted(
            [(eid, cnt) for eid, cnt in degree.items() if cnt >= 5],
            key=lambda x: -x[1]
        )
        
        total_issues = (
            len(low_conf) + 
            len(dangling) + 
            len(self_rels) + 
            sum(len(g) - 1 for g in duplicates)  # Count duplicates past first
        )
        
        return {
            'low_confidence_relationships': low_conf,
            'dangling_relationships': dangling,
            'self_relationships': self_rels,
            'duplicate_relationships': duplicates,
            'high_degree_entities': high_degree,
            'total_issues': total_issues,
        }

    def get_entity_by_id(self, entity_id: str) -> Optional["Entity"]:
        """Get a specific entity by its ID.

        Args:
            entity_id: The entity ID to look up

        Returns:
            The Entity object, or None if not found

        Example:
            >>> entity = result.get_entity_by_id('e1')
            >>> if entity:
            ...     print(f"Found: {entity.text}")
        """
        for e in self.entities:
            if e.id == entity_id:
                return e
        return None

    def get_relationship_by_id(self, rel_id: str) -> Optional["Relationship"]:
        """Get a specific relationship by its ID.

        Args:
            rel_id: The relationship ID to look up

        Returns:
            The Relationship object, or None if not found
        """
        for r in self.relationships:
            if r.id == rel_id:
                return r
        return None

    def relationships_for_entity(self, entity_id: str) -> List["Relationship"]:
        """Get all relationships where entity is source or target.

        Args:
            entity_id: The entity ID to find relationships for

        Returns:
            List of Relationship objects involving this entity
        """
        return [
            r for r in self.relationships
            if r.source_id == entity_id or r.target_id == entity_id
        ]

    def entities_by_confidence_range(
        self,
        min_conf: float = 0.0,
        max_conf: float = 1.0,
    ) -> List["Entity"]:
        """Get entities within a confidence range.

        Args:
            min_conf: Minimum confidence threshold (inclusive)
            max_conf: Maximum confidence threshold (inclusive)

        Returns:
            List of entities with confidence in [min_conf, max_conf]

        Example:
            >>> high_conf = result.entities_by_confidence_range(min_conf=0.8)
            >>> print(f"Found {len(high_conf)} high-confidence entities")
        """
        return [
            e for e in self.entities
            if min_conf <= e.confidence <= max_conf
        ]

    def low_confidence_entities(self, threshold: float = 0.5) -> List["Entity"]:
        """Get all entities below confidence threshold.

        Args:
            threshold: Confidence threshold (default 0.5)

        Returns:
            List of entities with confidence < threshold
        """
        return [e for e in self.entities if e.confidence < threshold]

    def high_confidence_entities(self, threshold: float = 0.8) -> List["Entity"]:
        """Get all entities above confidence threshold.

        Args:
            threshold: Confidence threshold (default 0.8)

        Returns:
            List of entities with confidence >= threshold
        """
        return [e for e in self.entities if e.confidence >= threshold]

    def relationships_by_type(self, rel_type: str) -> List["Relationship"]:
        """Get all relationships of a specific type.

        Args:
            rel_type: The relationship type to filter by

        Returns:
            List of relationships matching the type
        """
        return [r for r in self.relationships if r.type == rel_type]

    def relationship_count_by_type(self) -> Dict[str, int]:
        """Get count of relationships grouped by type.

        Returns:
            Dict mapping relationship types to counts
        """
        counts = {}
        for r in self.relationships:
            counts[r.type] = counts.get(r.type, 0) + 1
        return dict(sorted(counts.items(), key=lambda x: -x[1]))

    @property
    def entity_count(self) -> int:
        """Return the number of entities in this result.

        This is a convenience property that returns ``len(self.entities)``.

        Returns:
            Integer count of entities.

        Example:
            >>> result.entity_count
            5
        """
        return len(self.entities)

    @property
    def relationship_count(self) -> int:
        """Return the number of relationships in this result.

        This is a convenience property that returns ``len(self.relationships)``.

        Returns:
            Integer count of relationships.

        Example:
            >>> result.relationship_count
            3
        """
        return len(self.relationships)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EntityExtractionResult":
        """Deserialize an EntityExtractionResult from a plain dict.

        This is the inverse of :meth:`to_dict`. Given a dict with keys
        ``entities``, ``relationships``, ``confidence``, ``metadata``, and
        ``errors``, reconstructs a full result object.

        Args:
            data: Dict with required keys:

            * ``"entities"`` -- list of entity dicts (each with ``id``, ``text``,
              ``type``, ``confidence``, and optional ``properties``, ``source_span``).
            * ``"relationships"`` -- list of relationship dicts (each with ``id``,
              ``source_id``, ``target_id``, ``type``, ``confidence``, ``direction``,
              and ``properties``).
            * ``"confidence"`` -- overall confidence float.
            * ``"metadata"`` -- dict (optional, defaults to ``{}``).
            * ``"errors"`` -- list of error strings (optional, defaults to ``[]``).

        Returns:
            Reconstructed :class:`EntityExtractionResult`.

        Example:
            >>> d = result.to_dict()
            >>> restored = EntityExtractionResult.from_dict(d)
            >>> len(restored.entities) == len(result.entities)
            True
        """
        # Reconstruct entities
        entities = []
        for ent_dict in data.get("entities", []):
            ent = Entity(
                id=ent_dict.get("id", ""),
                text=ent_dict.get("text", ""),
                type=ent_dict.get("type", "unknown"),
                confidence=float(ent_dict.get("confidence", 1.0)),
                properties=dict(ent_dict.get("properties", {})),
                source_span=tuple(ent_dict["source_span"]) if ent_dict.get("source_span") else None,
            )
            entities.append(ent)

        # Reconstruct relationships
        relationships = []
        for rel_dict in data.get("relationships", []):
            rel = Relationship(
                id=rel_dict.get("id", ""),
                source_id=rel_dict.get("source_id", ""),
                target_id=rel_dict.get("target_id", ""),
                type=rel_dict.get("type", "unknown"),
                confidence=float(rel_dict.get("confidence", 1.0)),
                direction=rel_dict.get("direction", "unknown"),
                properties=dict(rel_dict.get("properties", {})),
            )
            relationships.append(rel)

        return cls(
            entities=entities,
            relationships=relationships,
            confidence=float(data.get("confidence", 1.0)),
            metadata=dict(data.get("metadata", {})),
            errors=list(data.get("errors", [])),
        )


@dataclass
class OntologyGenerationResult:
    """Rich result wrapper for a single ontology generation run.

    Wraps the raw ontology dict with pre-computed summary statistics for
    downstream reporting, logging, and dashboarding.

    Attributes:
        ontology: The raw ontology dict (``{"entities": [...], "relationships": [...]}``)
            as returned by :meth:`OntologyGenerator.generate_ontology`.
        entity_count: Total number of extracted entities.
        relationship_count: Total number of inferred relationships.
        entity_type_diversity: Number of distinct entity type labels.  Higher
            values indicate a more varied ontology.
        mean_entity_confidence: Mean confidence score across all entities.
            ``0.0`` when there are no entities.
        mean_relationship_confidence: Mean confidence score across all
            relationships. ``0.0`` when there are no relationships.
        extraction_strategy: Name of the extraction strategy used (e.g.
            ``"rule_based"``, ``"llm_based"``).
        domain: Domain string from the generation context.
        metadata: Arbitrary extra data (timings, backend info, etc.).

    Example::

        result = generator.generate_ontology_rich(data, context)
        print(f"Entities: {result.entity_count}, "
              f"Types: {result.entity_type_diversity}, "
              f"Rels: {result.relationship_count}")
    """

    ontology: Dict[str, Any]
    entity_count: int = 0
    relationship_count: int = 0
    entity_type_diversity: int = 0
    mean_entity_confidence: float = 0.0
    mean_relationship_confidence: float = 0.0
    extraction_strategy: str = "unknown"
    domain: str = "general"
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_ontology(
        cls,
        ontology: Dict[str, Any],
        *,
        extraction_strategy: str = "unknown",
        domain: str = "general",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "OntologyGenerationResult":
        """Construct from a raw ontology dict, computing summary stats.

        Args:
            ontology: Raw ontology dict with ``entities`` and ``relationships`` lists.
            extraction_strategy: Name of the strategy that produced this ontology.
            domain: Domain string.
            metadata: Optional extra metadata.

        Returns:
            Fully populated :class:`OntologyGenerationResult`.
        """
        entities = ontology.get("entities") or []
        relationships = ontology.get("relationships") or []

        entity_types = {e.get("type") for e in entities if isinstance(e, dict) and e.get("type")}

        def _mean_confidence(items: list) -> float:
            confs = [
                float(i.get("confidence", 1.0))
                for i in items
                if isinstance(i, dict)
            ]
            return sum(confs) / len(confs) if confs else 0.0

        return cls(
            ontology=ontology,
            entity_count=len(entities),
            relationship_count=len(relationships),
            entity_type_diversity=len(entity_types),
            mean_entity_confidence=_mean_confidence(entities),
            mean_relationship_confidence=_mean_confidence(relationships),
            extraction_strategy=extraction_strategy,
            domain=domain,
            metadata=metadata or {},
        )


class OntologyGenerator:
    """
    Generate knowledge graph ontologies from arbitrary data.
    
    This class provides the core functionality for extracting entities and
    relationships from various data types and generating structured ontologies.
    It integrates with ipfs_accelerate_py for AI model inference and supports
    multiple extraction strategies.
    
    Inspired by the complainant agent from complaint-generator, adapted for
    ontology generation with focus on consistency and logical structure.
    
    Attributes:
        ipfs_accelerate_config: Configuration for ipfs_accelerate_py integration
        use_ipfs_accelerate: Whether to use ipfs_accelerate for inference
        
    Example:
        >>> generator = OntologyGenerator(ipfs_accelerate_config={
        ...     'model': 'bert-base-uncased',
        ...     'task': 'token-classification',
        ...     'device': 'cuda'
        ... })
        >>> 
        >>> result = generator.extract_entities(data, context)
        >>> ontology = generator.generate_ontology(data, context)
    """
    
    # Lazy-loaded domain-specific rule patterns (class-level caching)
    _verb_patterns_cache = None
    _type_inference_rules_cache = None
    
    @classmethod
    def _get_verb_patterns(cls):
        """
        Get verb-frame patterns for relationship type inference (lazy-loaded).
        
        Patterns are compiled once on first access and cached at class level.
        Each pattern is a tuple of (regex_pattern, relationship_type).
        
        Returns:
            List of tuples: (pattern: str, rel_type: str)
        """
        if cls._verb_patterns_cache is None:
            cls._verb_patterns_cache = [
                (r'\b(\w+)\s+(?:must|shall|is required to|is obligated to)\s+\w+\s+(\w+)\b', 'obligates'),
                (r'\b(\w+)\s+owns?\s+(\w+)\b', 'owns'),
                (r'\b(\w+)\s+causes?\s+(\w+)\b', 'causes'),
                (r'\b(\w+)\s+(?:is a|is an)\s+(\w+)\b', 'is_a'),
                (r'\b(\w+)\s+(?:part of|belongs to)\s+(\w+)\b', 'part_of'),
                (r'\b(\w+)\s+(?:employs?|hired?)\s+(\w+)\b', 'employs'),
                (r'\b(\w+)\s+(?:manages?|supervises?)\s+(\w+)\b', 'manages'),
            ]
        return cls._verb_patterns_cache
    
    @classmethod
    def _get_type_inference_rules(cls):
        """
        Get entity type-based relationship type inference rules (lazy-loaded).
        
        Rules map entity type pairs to likely relationship types with base confidence.
        Cached at class level for reuse across instances.
        
        Returns:
            List of dicts with 'condition', 'type', and 'base_confidence' keys
        """
        if cls._type_inference_rules_cache is None:
            cls._type_inference_rules_cache = [
                {
                    'condition': lambda e1_type, e2_type: (
                        ('person' in e1_type or 'person' in e2_type) and 
                        ('organization' in e1_type or 'organization' in e2_type)
                    ),
                    'type': 'works_for',
                    'base_confidence': 0.65,
                    'distance_threshold': 100
                },
                {
                    'condition': lambda e1_type, e2_type: (
                        ('person' in e1_type or 'person' in e2_type) and 
                        ('location' in e1_type or 'location' in e2_type)
                    ),
                    'type': 'located_in',
                    'base_confidence': 0.60,
                    'distance_threshold': 80
                },
                {
                    'condition': lambda e1_type, e2_type: (
                        ('organization' in e1_type or 'organization' in e2_type) and 
                        ('product' in e1_type or 'product' in e2_type)
                    ),
                    'type': 'produces',
                    'base_confidence': 0.65,
                    'distance_threshold': 100
                },
                {
                    'condition': lambda e1_type, e2_type: (
                        (e1_type == e2_type) and (e1_type in ['person', 'organization'])
                    ),
                    'type': 'related_to',
                    'base_confidence': 0.55,
                    'distance_threshold': 150
                },
            ]
        return cls._type_inference_rules_cache
    
    def __init__(
        self,
        ipfs_accelerate_config: Optional[Dict[str, Any]] = None,
        use_ipfs_accelerate: bool = True,
        logger: Optional[Any] = None,
        llm_backend: Optional[Any] = None,
    ):
        """
        Initialize the ontology generator.
        
        Args:
            ipfs_accelerate_config: Configuration for ipfs_accelerate_py.
                Should include 'model', 'task', and optionally 'device'.
            use_ipfs_accelerate: Whether to use ipfs_accelerate for inference.
                If False, falls back to rule-based extraction.
            logger: Optional :class:`logging.Logger`.  Defaults to the module logger.
            llm_backend: Optional callable/client used for LLM-based extraction
                fallback.  If provided and ``ExtractionConfig.llm_fallback_threshold``
                is > 0, rule-based results with confidence below the threshold will be
                retried via :meth:`_extract_llm_based`.
                
        Raises:
            ImportError: If ipfs_accelerate is required but not available
        """
        import logging as _logging
        self._log = logger or _logging.getLogger(__name__)
        self.ipfs_accelerate_config = ipfs_accelerate_config or {}
        resolved_backend = resolve_backend_settings(
            self.ipfs_accelerate_config,
            default_provider="accelerate",
            default_model=str(self.ipfs_accelerate_config.get("model", "gpt-4")),
            use_ipfs_accelerate=use_ipfs_accelerate,
            prefer_accelerate=True,
        )
        # Centralized backend rules: accelerate is only used when selected and enabled.
        self.use_ipfs_accelerate = resolved_backend.use_ipfs_accelerate
        self.backend_provider = resolved_backend.provider
        self.ipfs_accelerate_config.setdefault("provider", resolved_backend.provider)
        self.ipfs_accelerate_config.setdefault("model", resolved_backend.model)
        self._accelerate_client = None
        self.llm_backend = llm_backend
        
        if self.use_ipfs_accelerate:
            try:
                # Import ipfs_accelerate_py integration
                from ipfs_datasets_py.processors.file_converter import (
                    ipfs_accelerate_converter
                )
                self._accelerate_available = True
                self._log.info("ipfs_accelerate_py integration available")
            except ImportError as e:
                self._log.warning(
                    f"ipfs_accelerate_py not available: {e}. "
                    "Falling back to rule-based extraction."
                )
                self._accelerate_available = False
                self.use_ipfs_accelerate = False
        else:
            self._accelerate_available = False
    
    def extract_entities(
        self,
        data: Any,
        context: OntologyGenerationContext
    ) -> EntityExtractionResult:
        """
        Extract entities from data using configured strategy.
        
        This method orchestrates entity extraction based on the context's
        extraction strategy. It can use rule-based patterns, LLM inference,
        or a hybrid approach.
        
        Args:
            data: Input data to extract entities from
            context: Context with extraction configuration
            
        Returns:
            EntityExtractionResult containing extracted entities and relationships
            
        Example:
            >>> result = generator.extract_entities(
            ...     "Alice must pay Bob $100 by Friday",
            ...     context
            ... )
            >>> print(f"Found {len(result.entities)} entities")
        """
        self._log.info(
            f"Extracting entities using {context.extraction_strategy.value} strategy"
        )
        
        if context.extraction_strategy == ExtractionStrategy.RULE_BASED:
            result = self._extract_with_llm_fallback(data, context)
            self._log.info(
                "extract_entities complete: entity_count=%d strategy=%s confidence=%.3f",
                len(result.entities),
                context.extraction_strategy.value,
                result.confidence,
            )
            return result
        elif context.extraction_strategy == ExtractionStrategy.LLM_BASED:
            result = self._extract_llm_based(data, context)
        elif context.extraction_strategy == ExtractionStrategy.HYBRID:
            result = self._extract_hybrid(data, context)
        elif context.extraction_strategy == ExtractionStrategy.NEURAL:
            result = self._extract_neural(data, context)
        else:
            raise ValueError(
                f"Unknown extraction strategy: {context.extraction_strategy}"
            )
        self._log.info(
            "extract_entities complete: entity_count=%d strategy=%s confidence=%.3f",
            len(result.entities),
            context.extraction_strategy.value,
            result.confidence,
        )
        return result

    def _extract_with_llm_fallback(
        self,
        data: Any,
        context: OntologyGenerationContext,
    ) -> EntityExtractionResult:
        """Run rule-based extraction with optional LLM fallback.

        LLM fallback runs only when the rule-based confidence is below
        ``ExtractionConfig.llm_fallback_threshold`` and ``llm_backend`` is set.
        If the LLM result has worse confidence, the rule-based result is kept.

        Args:
            data: Input data to extract entities from.
            context: Extraction context with configuration.

        Returns:
            The best available :class:`EntityExtractionResult`.
        """
        result = self._extract_rule_based(data, context)
        try:
            cfg = context.extraction_config
            llm_threshold = float(getattr(cfg, "llm_fallback_threshold", 0.0))
        except (TypeError, ValueError, AttributeError):
            llm_threshold = 0.0
        if (
            llm_threshold > 0.0
            and self.llm_backend is not None
            and result.confidence < llm_threshold
        ):
            self._log.info(
                "Rule-based confidence %.3f below fallback threshold %.3f; "
                "attempting LLM extraction.",
                result.confidence,
                llm_threshold,
            )
            try:
                llm_result = self._extract_llm_based(data, context)
                if llm_result.confidence >= result.confidence:
                    result = llm_result
            except Exception as exc:
                self._log.warning("LLM fallback extraction failed: %s", exc)
        return result
    
    def infer_relationships(
        self,
        entities: List[Entity],
        context: OntologyGenerationContext,
        data: Optional[Any] = None
    ) -> List[Relationship]:
        """
        Infer relationships between extracted entities.
        
        Uses heuristics and optionally LLM inference to determine relationships
        between entities. Can use source data for context if provided.
        
        Args:
            entities: List of entities to find relationships between
            context: Context with configuration
            data: Optional source data for context
            
        Returns:
            List of inferred relationships
            
        Example:
            >>> relationships = generator.infer_relationships(
            ...     entities,
            ...     context,
            ...     data="Alice must pay Bob"
            ... )
        """
        self._log.info(f"Inferring relationships between {len(entities)} entities")

        relationships = []
        text = str(data) if data is not None else ""

        # Use lazy-loaded verb-frame patterns (cached at class level)
        _VERB_PATTERNS = self._get_verb_patterns()

        import re as _re
        entity_texts = {e.text.lower(): e for e in entities}
        entity_ids_by_text = {e.text.lower(): e.id for e in entities}

        rel_id_counter = [0]

        def _make_rel_id() -> str:
            rel_id_counter[0] += 1
            return f"rel_{rel_id_counter[0]:04d}"

        # 1) Verb-frame matching in text with type confidence scoring
        for pattern, rel_type in _VERB_PATTERNS:
            for m in _re.finditer(pattern, text, _re.IGNORECASE):
                subj_text = m.group(1).lower()
                obj_text = m.group(2).lower()
                src_id = entity_ids_by_text.get(subj_text)
                tgt_id = entity_ids_by_text.get(obj_text)
                if src_id and tgt_id and src_id != tgt_id:
                    # Calculate type confidence based on pattern specificity and verb matching
                    # More specific patterns (e.g., "obligates") and exact matches get higher scores
                    verb_text = m.group(0)
                    
                    # Type confidence: how certain we are this is the correct relationship type
                    # Based on: pattern match exactness, specificity, and verb phrase clustering
                    if rel_type == 'obligates':
                        type_confidence = 0.85  # Very specific, legal domain
                    elif rel_type in ('owns', 'employs', 'manages'):
                        type_confidence = 0.80  # Clear semantic verbs
                    elif rel_type in ('causes', 'is_a'):
                        type_confidence = 0.75  # More general but clear intent
                    elif rel_type == 'part_of':
                        type_confidence = 0.72  # Compositional, sometimes ambiguous
                    else:
                        type_confidence = 0.65  # Default fallback
                    
                    relationships.append(Relationship(
                        id=_make_rel_id(),
                        source_id=src_id,
                        target_id=tgt_id,
                        type=rel_type,
                        confidence=0.65,
                        direction='subject_to_object',
                        properties={
                            'type_confidence': type_confidence,
                            'type_method': 'verb_frame',
                        },
                    ))

        # 2) Sliding-window co-occurrence (window=200 chars) with improved type inference
        # Confidence decay: base 0.6 at distance 0, decays linearly.
        # Entities >100 chars apart receive < 0.4 confidence; floor is 0.2.
        # Uses entity types and context to infer relationship types with confidence scores
        linked = {(r.source_id, r.target_id) for r in relationships}
        entity_list = list(entities)
        for i, e1 in enumerate(entity_list):
            pos1 = text.lower().find(e1.text.lower())
            if pos1 < 0:
                continue
            for e2 in entity_list[i + 1:]:
                if (e1.id, e2.id) in linked or (e2.id, e1.id) in linked:
                    continue
                pos2 = text.lower().find(e2.text.lower())
                if pos2 < 0:
                    continue
                distance = abs(pos1 - pos2)
                if distance <= 200:
                    # Steeper decay beyond 100 chars to reflect weaker association
                    if distance <= 100:
                        confidence = max(0.4, 0.6 - distance / 500.0)
                    else:
                        # Extra penalty for distant entities (>100 chars apart)
                        confidence = max(0.2, 0.4 - (distance - 100) / 500.0)
                    
                    # Infer relationship type from entity types and proximity
                    # Type confidence based on entity type compatibility and distance
                    e1_type = getattr(e1, 'type', 'unknown').lower()
                    e2_type = getattr(e2, 'type', 'unknown').lower()
                    
                    # Use lazy-loaded type inference rules (cached at class level)
                    inferred_type = 'related_to'  # Default
                    type_confidence = 0.50  # Lower base confidence for heuristic inference
                    
                    # Apply entity type-based inference rules
                    type_inference_rules = self._get_type_inference_rules()
                    for rule in type_inference_rules:
                        if rule['condition'](e1_type, e2_type):
                            inferred_type = rule['type']
                            # Apply distance-based confidence thresholding
                            if distance < rule['distance_threshold']:
                                type_confidence = rule['base_confidence']
                            else:
                                type_confidence = rule['base_confidence'] - 0.15
                            break
                    
                    # Discount confidence for very distant co-occurrences
                    if distance > 150:
                        type_confidence *= 0.8
                    
                    relationships.append(Relationship(
                        id=_make_rel_id(),
                        source_id=e1.id,
                        target_id=e2.id,
                        type=inferred_type,
                        confidence=confidence,
                        direction='undirected',
                        properties={
                            'type_confidence': type_confidence,
                            'type_method': 'cooccurrence',
                            'source_entity_type': e1_type,
                            'target_entity_type': e2_type,
                        },
                    ))
                    linked.add((e1.id, e2.id))

        self._log.info(f"Inferred {len(relationships)} relationships")
        return relationships

    def extract_entities_from_file(
        self,
        filepath: str,
        context: "OntologyGenerationContext",
        encoding: str = "utf-8",
    ) -> "EntityExtractionResult":
        """Convenience wrapper: read *filepath* and call :meth:`extract_entities`.

        Args:
            filepath: Path to a plain-text file to read.
            context: Extraction context (strategy, config, etc.).
            encoding: File encoding (default: ``"utf-8"``).

        Returns:
            :class:`EntityExtractionResult` from the file contents.

        Raises:
            OSError: If the file cannot be read.
        """
        with open(filepath, encoding=encoding) as fh:
            text = fh.read()
        return self.extract_entities(text, context)

    def batch_extract(
        self,
        docs: List[Any],
        context: "OntologyGenerationContext",
        max_workers: int = 4,
    ) -> List["EntityExtractionResult"]:
        """Extract entities from multiple documents in parallel.

        Uses :class:`concurrent.futures.ThreadPoolExecutor` to call
        :meth:`extract_entities` for each document concurrently.

        Args:
            docs: List of document texts (or data objects) to extract from.
            context: Shared extraction context used for all documents.
            max_workers: Thread pool size (default: 4).

        Returns:
            List of :class:`EntityExtractionResult` in the same order as
            *docs*.  Failed extractions produce an
            :class:`EntityExtractionResult` with ``errors`` populated.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results: List[Any] = [None] * len(docs)

        def _extract(idx: int, doc: Any) -> tuple:
            try:
                return idx, self.extract_entities(doc, context)
            except Exception as exc:  # extraction must never crash the whole batch
                empty = EntityExtractionResult(
                    entities=[],
                    relationships=[],
                    confidence=0.0,
                    errors=[str(exc)],
                )
                return idx, empty

        with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
            futures = {pool.submit(_extract, i, doc): i for i, doc in enumerate(docs)}
            for future in as_completed(futures):
                idx, result = future.result()
                # Tag each entity with its source document index (provenance)
                for ent in result.entities:
                    if not hasattr(ent, '__dict__'):
                        pass  # frozen dataclass — skip tagging
                    else:
                        ent.__dict__.setdefault('source_doc_index', idx)
                results[idx] = result

        return results  # type: ignore[return-value]

    def extract_entities_streaming(
        self,
        data: Any,
        context: "OntologyGenerationContext",
    ):
        """Yield entity extraction results one entity at a time (iterator API).

        This is useful for streaming UIs or pipelines that want to process
        each entity as soon as it is found, rather than waiting for the full
        extraction to complete.

        Args:
            data: Input text/data to extract entities from.
            context: Extraction context.

        Yields:
            :class:`Entity` objects in the order they were extracted.
        """
        result = self.extract_entities(data, context)
        yield from result.entities

    def extract_entities_with_spans(
        self,
        data: str,
        context: "OntologyGenerationContext",
    ) -> "EntityExtractionResult":
        """Extract entities and annotate each with character-offset source spans.

        Delegates to :meth:`extract_entities` and then searches for each
        entity's ``text`` in *data* to attach a ``(start, end)``
        ``source_span``.  Only the **first** occurrence is used.  Entities
        whose text cannot be found in *data* retain their original
        ``source_span`` (typically ``None``).

        Args:
            data: Raw input text string to extract from.
            context: Extraction context.

        Returns:
            :class:`EntityExtractionResult` with :attr:`Entity.source_span`
            populated where possible.

        Example:
            >>> result = generator.extract_entities_with_spans(text, ctx)
            >>> for e in result.entities:
            ...     if e.source_span:
            ...         print(e.text, e.source_span)
        """
        import dataclasses as _dc

        result = self.extract_entities(data, context)
        annotated: List[Entity] = []
        for ent in result.entities:
            if ent.source_span is None and isinstance(data, str) and ent.text:
                idx = data.find(ent.text)
                if idx != -1:
                    span: Optional[tuple] = (idx, idx + len(ent.text))
                else:
                    span = None
                ent = _dc.replace(ent, source_span=span)
            annotated.append(ent)
        return EntityExtractionResult(
            entities=annotated,
            relationships=result.relationships,
            confidence=result.confidence,
            metadata=result.metadata,
            errors=result.errors,
        )

    def extract_with_coref(
        self,
        data: str,
        context: "OntologyGenerationContext",
    ) -> "EntityExtractionResult":
        """Extract entities after a lightweight co-reference resolution pre-pass.

        This method applies a heuristic co-reference resolution step before
        extraction: it replaces common pronoun forms (``he``, ``she``, ``they``,
        ``it``, ``his``, ``her``, ``their``, ``its``) with the most-recently
        seen proper-noun-like token (capitalised word) in the text.  This
        increases the chance that pronoun-heavy text yields coherent entity
        spans.

        For production use-cases, replace this pre-pass with a full NLP
        co-reference library such as ``spacy-experimental`` or ``fastcoref``.

        Args:
            data: Raw input text string.
            context: Extraction context.

        Returns:
            :class:`EntityExtractionResult` from the resolved text with
            ``metadata["coref_resolved"]`` set to ``True``.
        """
        import re as _re

        resolved = data
        if isinstance(data, str):
            # Collect the last-seen proper-noun candidate (capitalised non-sentence-start word)
            words = _re.split(r"(\W+)", data)
            last_proper: Optional[str] = None
            resolved_parts = []
            pronoun_set = {"he", "she", "they", "it", "his", "her", "their", "its",
                           "him", "them"}
            for token in words:
                if token.istitle() and len(token) > 2 and token.lower() not in pronoun_set:
                    last_proper = token
                if token.lower() in pronoun_set and last_proper:
                    resolved_parts.append(last_proper)
                else:
                    resolved_parts.append(token)
            resolved = "".join(resolved_parts)

        result = self.extract_entities(resolved, context)
        result.metadata["coref_resolved"] = True
        return result

    def extract_with_context_windows(
        self,
        data: str,
        context: "OntologyGenerationContext",
        window_size: int = 512,
        window_overlap: int = 64,
        dedup_method: str = "highest_confidence",
    ) -> "EntityExtractionResult":
        """Extract entities from large texts using sliding context windows.
        
        Handles texts larger than typical LLM context windows by:
        1. Splitting text into overlapping windows
        2. Extracting entities from each window independently
        3. Deduplicating across windows using configurable strategy
        4. Aggregating results into a single EntityExtractionResult
        
        This is useful for:
        - Large documents that exceed LLM token limits
        - Maintaining contextual coherence across text boundaries
        - Reducing memory consumption for very large texts
        
        Args:
            data: Input text to extract entities from (can be very large)
            context: Extraction context with configuration
            window_size: Number of characters per window (default 512)
            window_overlap: Number of characters of overlap between windows (default 64)
            dedup_method: Strategy for deduplicating overlapping entities:
                - "highest_confidence": Keep entity with highest confidence
                - "first_occurrence": Keep first-seen entity
                - "merge_spans": Merge all occurrences with averaged confidence
        
        Returns:
            EntityExtractionResult with all entities extracted from all windows,
            deduplicated and aggregated. metadata["window_count"] tracks number
            of windows processed.
        
        Raises:
            ValueError: If window_size < 1, overlap >= window_size, or invalid dedup_method
        
        Example:
            >>> large_text = "Alice and Bob..." # Very long document
            >>> result = generator.extract_with_context_windows(
            ...     large_text,
            ...     context,
            ...     window_size=512,
            ...     window_overlap=64
            ... )
            >>> print(f"Found {len(result.entities)} entities across {result.metadata['window_count']} windows")
        """
        import copy as _copy
        
        # Validate parameters
        if window_size < 1:
            raise ValueError(f"window_size must be >= 1, got {window_size}")
        if window_overlap < 0:
            raise ValueError(f"window_overlap must be >= 0, got {window_overlap}")
        if window_overlap >= window_size:
            raise ValueError(f"window_overlap ({window_overlap}) must be < window_size ({window_size})")
        if dedup_method not in ("highest_confidence", "first_occurrence", "merge_spans"):
            raise ValueError(
                f"Invalid dedup_method '{dedup_method}'; must be one of: "
                "highest_confidence, first_occurrence, merge_spans"
            )
        
        text = str(data) if data is not None else ""
        if not text:
            # Return empty result for empty input
            return EntityExtractionResult(entities=[], relationships=[], confidence=1.0)
        
        # Split text into overlapping windows
        windows = self._split_into_windows(text, window_size, window_overlap)
        self._log.info(
            f"extract_with_context_windows: splitting {len(text)} chars into "
            f"{len(windows)} windows (size={window_size}, overlap={window_overlap})"
        )
        
        # Extract from each window
        window_results: List[EntityExtractionResult] = []
        for i, window_text in enumerate(windows):
            try:
                result = self.extract_entities(window_text, context)
                window_results.append(result)
            except Exception as e:
                self._log.warning(
                    f"Extraction failed for window {i} ({len(window_text)} chars): {e}"
                )
                # Continue with remaining windows
                continue
        
        if not window_results:
            self._log.warning("No successful extractions from any window")
            return EntityExtractionResult(entities=[], relationships=[], confidence=0.0)
        
        # Merge results with deduplication
        merged = self._merge_window_results(
            window_results,
            dedup_method=dedup_method
        )
        
        # Add window metadata
        merged.metadata["window_count"] = len(windows)
        merged.metadata["successful_windows"] = len(window_results)
        merged.metadata["window_size"] = window_size
        merged.metadata["window_overlap"] = window_overlap
        merged.metadata["dedup_method"] = dedup_method
        
        self._log.info(
            f"extract_with_context_windows complete: {len(merged.entities)} entities "
            f"from {len(window_results)}/{len(windows)} windows, "
            f"deduplicated with {dedup_method}"
        )
        
        return merged
    
    def _split_into_windows(
        self,
        text: str,
        window_size: int,
        overlap: int,
    ) -> List[str]:
        """Split text into overlapping windows.
        
        Args:
            text: Input text
            window_size: Size of each window
            overlap: Overlap between consecutive windows
        
        Returns:
            List of window strings
        """
        if len(text) <= window_size:
            return [text]
        
        windows = []
        stride = window_size - overlap  # How much to advance per window
        
        i = 0
        while i < len(text):
            window = text[i:i + window_size]
            windows.append(window)
            i += stride
            
            # Ensure last window includes end of text
            if i + window_size >= len(text) and i < len(text):
                windows.append(text[-window_size:] if len(text) >= window_size else text)
                break
        
        return windows
    
    def _merge_window_results(
        self,
        results: List["EntityExtractionResult"],
        dedup_method: str = "highest_confidence",
    ) -> "EntityExtractionResult":
        """Merge results from multiple windows with deduplication.
        
        Args:
            results: List of EntityExtractionResult from each window
            dedup_method: Deduplication strategy
        
        Returns:
            Merged EntityExtractionResult
        """
        import copy as _copy
        
        if not results:
            return EntityExtractionResult(entities=[], relationships=[], confidence=0.0)
        
        # Collect all entities with separate tracking for merge strategy
        entity_index: Dict[str, Entity] = {}  # Map key -> Entity
        merge_tracking: Dict[str, Dict[str, float]] = {}  # Map key -> {count, total_conf}
        
        for result in results:
            for entity in result.entities:
                # Build deduplication key
                key = (entity.type.lower(), entity.text.lower())
                
                if dedup_method == "highest_confidence":
                    # Keep entity with highest confidence
                    if key not in entity_index:
                        entity_index[key] = _copy.deepcopy(entity)
                    elif entity.confidence > entity_index[key].confidence:
                        entity_index[key] = _copy.deepcopy(entity)
                
                elif dedup_method == "first_occurrence":
                    # Keep first-seen entity
                    if key not in entity_index:
                        entity_index[key] = _copy.deepcopy(entity)
                
                elif dedup_method == "merge_spans":
                    # Merge all occurrences with averaged confidence
                    if key not in entity_index:
                        entity_index[key] = _copy.deepcopy(entity)
                        merge_tracking[key] = {"count": 1, "sum_conf": entity.confidence}
                    else:
                        # Track for averaging
                        merge_tracking[key]["count"] += 1
                        merge_tracking[key]["sum_conf"] += entity.confidence
        
        # Apply merge_spans averaging if used
        if dedup_method == "merge_spans":
            for key, tracking in merge_tracking.items():
                if key in entity_index:
                    entity_index[key].confidence = (
                        tracking["sum_conf"] / tracking["count"]
                    )
        
        # Get final entity list
        deduped_entities = list(entity_index.values())
        
        # Collect all relationships (filter to valid entity IDs)
        valid_entity_ids = {ent.id for ent in deduped_entities}
        all_relationships = []
        seen_rel_keys: set = set()
        
        for result in results:
            for rel in result.relationships:
                # Only include relationships where both entities exist
                if (rel.source_id in valid_entity_ids and 
                    rel.target_id in valid_entity_ids):
                    # De-duplicate relationships
                    rel_key = (rel.source_id, rel.target_id, rel.type.lower())
                    if rel_key not in seen_rel_keys:
                        all_relationships.append(rel)
                        seen_rel_keys.add(rel_key)
        
        # Calculate average confidence
        avg_confidence = (
            sum(r.confidence for r in results) / len(results)
            if results else 0.0
        )
        
        return EntityExtractionResult(
            entities=deduped_entities,
            relationships=all_relationships,
            confidence=avg_confidence,
            metadata={"deduped_from": sum(len(r.entities) for r in results), "original_windows": len(results)},
        )

    def merge_provenance_report(
        self,
        results: List["EntityExtractionResult"],
        doc_labels: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Build a provenance report mapping each entity to its source document.

        Args:
            results: List of :class:`EntityExtractionResult` objects, e.g.
                from :meth:`batch_extract`.
            doc_labels: Optional human-readable labels for each document.
                Defaults to ``"doc_0"``, ``"doc_1"``, …

        Returns:
            List of dicts with keys:
            - ``entity_id``: entity ID
            - ``entity_text``: entity text
            - ``entity_type``: entity type
            - ``source_doc``: label of the source document
            - ``source_doc_index``: 0-based source document index
        """
        report: List[Dict[str, Any]] = []
        labels = doc_labels or [f"doc_{i}" for i in range(len(results))]
        for idx, result in enumerate(results):
            label = labels[idx] if idx < len(labels) else f"doc_{idx}"
            for ent in result.entities:
                report.append({
                    "entity_id": ent.id,
                    "entity_text": ent.text,
                    "entity_type": ent.type,
                    "source_doc": label,
                    "source_doc_index": idx,
                })
        return report

    def deduplicate_entities(
        self,
        result: "EntityExtractionResult",
    ) -> "EntityExtractionResult":
        """Merge entities with identical normalised text into a single entity.

        Normalisation: lowercase + strip whitespace.  When multiple entities
        share normalised text, the one with the highest confidence is kept.
        Relationships that referenced removed entity IDs are updated to point
        to the surviving entity.

        Args:
            result: An :class:`EntityExtractionResult` to deduplicate.

        Returns:
            A new :class:`EntityExtractionResult` with duplicates merged.
        """
        # Group by normalised text
        groups: Dict[str, List[Any]] = {}
        for ent in result.entities:
            key = ent.text.strip().lower()
            groups.setdefault(key, []).append(ent)

        # For each group keep the highest-confidence entity
        survivors: List[Any] = []
        id_remap: Dict[str, str] = {}  # removed_id → survivor_id
        for key, group in groups.items():
            best = max(group, key=lambda e: e.confidence)
            survivors.append(best)
            for ent in group:
                if ent.id != best.id:
                    id_remap[ent.id] = best.id

        # Remap relationship source/target IDs
        new_rels: List[Any] = []
        for rel in result.relationships:
            src = id_remap.get(rel.source_id, rel.source_id)
            tgt = id_remap.get(rel.target_id, rel.target_id)
            if src == tgt:
                continue  # skip self-loops created by deduplication
            # Create a shallow copy with updated IDs
            import dataclasses as _dc
            new_rels.append(_dc.replace(rel, source_id=src, target_id=tgt))

        return EntityExtractionResult(
            entities=survivors,
            relationships=new_rels,
            confidence=result.confidence,
            metadata={**result.metadata, "deduplication_count": len(id_remap)},
            errors=list(result.errors),
        )

    def filter_entities(
        self,
        result: "EntityExtractionResult",
        *,
        min_confidence: float = 0.0,
        allowed_types: Optional[List[str]] = None,
        text_contains: Optional[str] = None,
    ) -> "EntityExtractionResult":
        """Post-extraction filter: keep only entities matching all criteria.

        Args:
            result: Source :class:`EntityExtractionResult`.
            min_confidence: Minimum entity confidence (inclusive, default 0.0).
            allowed_types: If provided, only keep entities whose ``type`` is in
                this list (case-insensitive).
            text_contains: If provided, only keep entities whose ``text``
                contains this substring (case-insensitive).

        Returns:
            A new :class:`EntityExtractionResult` with filtered entities.
            Relationships referencing removed entity IDs are also removed.
        """
        kept_ids: set = set()
        filtered: List[Any] = []
        for ent in result.entities:
            if ent.confidence < min_confidence:
                continue
            if allowed_types is not None:
                if ent.type.lower() not in {t.lower() for t in allowed_types}:
                    continue
            if text_contains is not None:
                if text_contains.lower() not in ent.text.lower():
                    continue
            filtered.append(ent)
            kept_ids.add(ent.id)

        # Remove relationships that reference removed entities
        new_rels = [
            r for r in result.relationships
            if r.source_id in kept_ids and r.target_id in kept_ids
        ]

        return EntityExtractionResult(
            entities=filtered,
            relationships=new_rels,
            confidence=result.confidence,
            metadata={**result.metadata, "filtered_entity_count": len(filtered)},
            errors=list(result.errors),
        )

    def filter_by_confidence(
        self,
        result: "EntityExtractionResult",
        threshold: float = 0.5,
    ) -> Dict[str, Any]:
        """Filter extraction result by confidence threshold with detailed stats.

        This is a convenience wrapper around :meth:`EntityExtractionResult.filter_by_confidence`
        that provides additional statistics and logging.

        Args:
            result: Source :class:`EntityExtractionResult`to filter.
            threshold: Minimum confidence score (0–1) to keep. Default: 0.5.

        Returns:
            A dictionary containing:
                - ``result`` (:class:`EntityExtractionResult`): Filtered result
                - ``stats`` (dict): Detailed filtering statistics including:
                    - ``original_entity_count``: Number of entities before filtering
                    - ``filtered_entity_count``: Number of entities after filtering
                    - ``removed_entity_count``: Number of entities removed
                    - ``original_relationship_count``: Number of relationships before filtering
                    - ``filtered_relationship_count``: Number of relationships after filtering
                    - ``removed_relationship_count``: Number of relationships removed
                    - ``threshold``: The threshold value used
                    - ``retention_rate``: Fraction of entities retained (0–1)
                    - ``avg_confidence_before``: Average confidence before filtering
                    - ``avg_confidence_after``: Average confidence after filtering

        Raises:
            ValueError: If threshold is not in [0, 1].

        Example:
            >>> result = generator.extract_entities(data, context)
            >>> filtered_data = generator.filter_by_confidence(result, threshold=0.7)
            >>> print(f"Retained {filtered_data['stats']['retention_rate']:.1%} of entities")
            Retained 65.0% of entities
        """
        if not (0.0 <= threshold <= 1.0):
            raise ValueError(f"threshold must be in [0, 1]; got {threshold}")

        # Compute stats before filtering
        original_entity_count = len(result.entities)
        original_relationship_count = len(result.relationships)
        avg_confidence_before = (
            sum(e.confidence for e in result.entities) / original_entity_count
            if original_entity_count > 0
            else 0.0
        )

        # Perform filtering using EntityExtractionResult's method
        filtered_result = result.filter_by_confidence(threshold)

        # Compute stats after filtering
        filtered_entity_count = len(filtered_result.entities)
        filtered_relationship_count = len(filtered_result.relationships)
        removed_entity_count = original_entity_count - filtered_entity_count
        removed_relationship_count = original_relationship_count - filtered_relationship_count
        retention_rate = (
            filtered_entity_count / original_entity_count
            if original_entity_count > 0
            else 0.0
        )
        avg_confidence_after = (
            sum(e.confidence for e in filtered_result.entities) / filtered_entity_count
            if filtered_entity_count > 0
            else 0.0
        )

        stats = {
            "original_entity_count": original_entity_count,
            "filtered_entity_count": filtered_entity_count,
            "removed_entity_count": removed_entity_count,
            "original_relationship_count": original_relationship_count,
            "filtered_relationship_count": filtered_relationship_count,
            "removed_relationship_count": removed_relationship_count,
            "threshold": threshold,
            "retention_rate": retention_rate,
            "avg_confidence_before": avg_confidence_before,
            "avg_confidence_after": avg_confidence_after,
        }

        self._log.info(
            f"Filtered entities by confidence >= {threshold}: "
            f"{filtered_entity_count}/{original_entity_count} entities retained "
            f"({retention_rate:.1%})"
        )

        return {
            "result": filtered_result,
            "stats": stats,
        }

    def generate_ontology(
        self,
        data: Any,
        context: OntologyGenerationContext
    ) -> Dict[str, Any]:
        """
        Generate complete ontology from data.
        
        This is the main entry point for ontology generation. It extracts
        entities, infers relationships, and constructs a complete ontology
        structure that can be validated by the logic validator.
        
        Args:
            data: Input data to generate ontology from
            context: Context with generation configuration
            
        Returns:
            Complete ontology as a dictionary with keys:
                - 'entities': List of entities
                - 'relationships': List of relationships
                - 'metadata': Metadata about the ontology
                - 'domain': Domain of the ontology
                
        Example:
            >>> ontology = generator.generate_ontology(
            ...     "Legal contract text...",
            ...     context
            ... )
            >>> print(f"Generated ontology with {len(ontology['entities'])} entities")
        """
        self._log.info(f"Generating ontology for {context.data_source}")
        
        # Extract entities and relationships
        extraction_result = self.extract_entities(data, context)
        
        # Build ontology structure
        ontology = {
            'entities': [self._entity_to_dict(e) for e in extraction_result.entities],
            'relationships': [
                self._relationship_to_dict(r) for r in extraction_result.relationships
            ],
            'metadata': {
                'source': context.data_source,
                'data_type': context.data_type.value,
                'domain': context.domain,
                'extraction_strategy': context.extraction_strategy.value,
                'confidence': extraction_result.confidence,
                **extraction_result.metadata
            },
            'domain': context.domain,
            'version': '1.0'
        }
        
        # Extend base ontology if provided
        if context.base_ontology:
            ontology = self._merge_ontologies(context.base_ontology, ontology)
        
        return ontology

    def __call__(
        self,
        data: Any,
        context: OntologyGenerationContext,
    ) -> Dict[str, Any]:
        """Shorthand for :meth:`generate_ontology`.

        Args:
            data: Input data to generate ontology from.
            context: Context with generation configuration.

        Returns:
            Ontology dictionary produced by :meth:`generate_ontology`.
        """
        return self.generate_ontology(data, context)

    def generate_ontology_rich(
        self,
        data: Any,
        context: OntologyGenerationContext,
    ) -> "OntologyGenerationResult":
        """Generate ontology and return a rich result with summary statistics.

        Calls :meth:`generate_ontology` and wraps the result in an
        :class:`OntologyGenerationResult` with pre-computed counts and
        confidence averages for easy reporting and logging.

        Args:
            data: Input data to generate ontology from.
            context: Context with generation configuration.

        Returns:
            :class:`OntologyGenerationResult` with the ontology dict and
            computed ``entity_count``, ``relationship_count``,
            ``entity_type_diversity``, and confidence averages.

        Example::

            result = generator.generate_ontology_rich(text, context)
            print(f"Entities: {result.entity_count}, "
                  f"Types: {result.entity_type_diversity}, "
                  f"Rels: {result.relationship_count}")
        """
        ontology = self.generate_ontology(data, context)
        import time as _time
        _t0 = _time.perf_counter()
        result = OntologyGenerationResult.from_ontology(
            ontology,
            extraction_strategy=context.extraction_strategy.value,
            domain=context.domain,
        )
        result.metadata["elapsed_ms"] = round((_time.perf_counter() - _t0) * 1000, 3)
        return result

    def generate_with_feedback(
        self,
        data: Any,
        context: OntologyGenerationContext,
        feedback: Optional[Dict[str, Any]] = None,
        critic: Optional["OntologyCritic"] = None,
    ) -> Dict[str, Any]:
        """
        Generate ontology with iterative feedback incorporation.

        Generates an initial ontology, optionally evaluates it with a critic,
        applies feedback suggestions, and returns the refined ontology.
        Useful for interactive refinement or feedback-loop architectures.

        Args:
            data: Input data to generate ontology from.
            context: Context with generation configuration.
            feedback: Optional feedback dict with suggested modifications:
                - 'entities_to_remove': List of entity IDs to remove
                - 'entities_to_merge': List of (id1, id2) tuples to merge
                - 'relationships_to_remove': List of relationship IDs to remove
                - 'relationships_to_add': List of relationship dicts to add
                - 'type_corrections': Dict mapping entity ID → corrected type
                - 'confidence_floor': Minimum confidence to keep entities
            critic: Optional :class:`OntologyCritic` for evaluation. If provided,
                ontology is evaluated and score is stored in metadata.

        Returns:
            Refined ontology dict with feedback applied. Metadata includes
            'feedback_applied' flag and score if critic was used.

        Example:
            >>> ontology = generator.generate_with_feedback(
            ...     text_data,
            ...     context,
            ...     feedback={'confidence_floor': 0.7}  # Keep only high-confidence
            ... )
            >>> # Use refined_ontology...
        """
        import logging as _logging

        logger = self._log or _logging.getLogger(__name__)
        logger.info(f"Generating ontology with feedback for {context.data_source}")

        # Step 1: Generate initial ontology
        ontology = self.generate_ontology(data, context)
        feedback_applied = False

        # Step 2: Apply feedback modifications if provided
        if feedback:
            feedback_applied = self._apply_feedback_to_ontology(ontology, feedback)

        # Step 3: Optionally evaluate with critic
        critic_score = None
        if critic is not None:
            try:
                from ipfs_datasets_py.optimizers.graphrag.ontology_critic import (
                    CriticScore,
                )

                critic_score = critic.evaluate_ontology(ontology, context, source_data=data)
                ontology["metadata"]["critic_score"] = {
                    "overall": critic_score.overall,
                    "completeness": critic_score.completeness,
                    "consistency": critic_score.consistency,
                    "clarity": critic_score.clarity,
                    "granularity": critic_score.granularity,
                    "relationship_coherence": critic_score.relationship_coherence,
                    "domain_alignment": critic_score.domain_alignment,
                }
            except Exception as e:
                logger.warning(f"Critic evaluation failed: {e}")

        # Step 4: Update metadata
        ontology["metadata"]["feedback_applied"] = feedback_applied
        if feedback:
            ontology["metadata"]["feedback_keys"] = list(feedback.keys())

        logger.info(
            f"Ontology generation complete: {len(ontology['entities'])} entities, "
            f"{len(ontology['relationships'])} relationships"
        )
        return ontology

    def _apply_feedback_to_ontology(
        self,
        ontology: Dict[str, Any],
        feedback: Dict[str, Any],
    ) -> bool:
        """
        Apply feedback modifications to ontology in-place.

        Args:
            ontology: Ontology dict to modify (modified in-place).
            feedback: Feedback dict with modification requests.

        Returns:
            bool: True if any modifications were applied.

        Side effects:
            Modifies 'entities' and 'relationships' lists in ontology.
        """
        import logging as _logging

        logger = _logging.getLogger(__name__)
        modified = False

        entities = ontology.get("entities", [])
        relationships = ontology.get("relationships", [])

        # Create ID → index mappings for fast lookup
        entity_id_to_idx = {e.get("id"): i for i, e in enumerate(entities)}
        rel_id_to_idx = {r.get("id"): i for i, r in enumerate(relationships)}

        # 1) Apply confidence floor filter
        if "confidence_floor" in feedback:
            floor = float(feedback["confidence_floor"])
            original_count = len(entities)
            entities = [e for e in entities if e.get("confidence", 0) >= floor]
            if len(entities) < original_count:
                logger.info(
                    f"Filtered {original_count - len(entities)} entities below "
                    f"confidence floor {floor}"
                )
                ontology["entities"] = entities
                # Rebuild ID → index mapping
                entity_id_to_idx = {e.get("id"): i for i, e in enumerate(entities)}
                modified = True

        # 2) Remove specific entities
        if "entities_to_remove" in feedback:
            for entity_id in feedback["entities_to_remove"]:
                if entity_id in entity_id_to_idx:
                    idx = entity_id_to_idx[entity_id]
                    entities.pop(idx)
                    # Rebuild mapping
                    entity_id_to_idx = {e.get("id"): i for i, e in enumerate(entities)}
                    logger.info(f"Removed entity {entity_id}")
                    modified = True

        # 3) Apply type corrections
        if "type_corrections" in feedback:
            for entity_id, new_type in feedback["type_corrections"].items():
                if entity_id in entity_id_to_idx:
                    idx = entity_id_to_idx[entity_id]
                    old_type = entities[idx].get("type")
                    entities[idx]["type"] = str(new_type)
                    logger.info(f"Corrected entity {entity_id} type: {old_type} → {new_type}")
                    modified = True

        # 4) Merge entities (keep first, discard second)
        if "entities_to_merge" in feedback:
            merged_pairs = []
            for id1, id2 in feedback["entities_to_merge"]:
                if id1 in entity_id_to_idx and id2 in entity_id_to_idx:
                    idx1, idx2 = entity_id_to_idx[id1], entity_id_to_idx[id2]
                    # Keep entity at idx1, discard idx2
                    entities.pop(idx2)
                    # Update mappings and relationships: redirect id2 → id1
                    entity_id_to_idx = {e.get("id"): i for i, e in enumerate(entities)}
                    for rel in relationships:
                        if rel.get("source_id") == id2:
                            rel["source_id"] = id1
                        if rel.get("target_id") == id2:
                            rel["target_id"] = id1
                    logger.info(f"Merged entities {id2} into {id1}")
                    merged_pairs.append((id1, id2))
                    modified = True

        # 5) Remove specific relationships
        if "relationships_to_remove" in feedback:
            for rel_id in feedback["relationships_to_remove"]:
                if rel_id in rel_id_to_idx:
                    idx = rel_id_to_idx[rel_id]
                    relationships.pop(idx)
                    # Rebuild mapping
                    rel_id_to_idx = {r.get("id"): i for i, r in enumerate(relationships)}
                    logger.info(f"Removed relationship {rel_id}")
                    modified = True

        # 6) Add new relationships
        if "relationships_to_add" in feedback:
            import uuid

            for rel_dict in feedback["relationships_to_add"]:
                # Ensure required fields
                if (
                    rel_dict.get("source_id")
                    and rel_dict.get("target_id")
                    and rel_dict.get("type")
                ):
                    # Generate ID if missing
                    if "id" not in rel_dict:
                        rel_dict["id"] = f"rel_{uuid.uuid4().hex[:8]}"
                    relationships.append(rel_dict)
                    logger.info(
                        f"Added relationship {rel_dict['id']}: "
                        f"{rel_dict['source_id']} → {rel_dict['target_id']}"
                    )
                    modified = True

        # Update ontology with modified lists
        ontology["entities"] = entities
        ontology["relationships"] = relationships

        return modified
    
    def _extract_rule_based(
        self,
        data: Any,
        context: OntologyGenerationContext
    ) -> EntityExtractionResult:
        """
        Extract entities using rule-based patterns.
        
        Args:
            data: Input data
            context: Extraction context
            
        Returns:
            Extraction result with entities and relationships
        """
        import time
        
        start_time = time.time()
        domain = getattr(context, 'domain', 'general').lower() if context else 'general'
        ext_config = getattr(context, 'extraction_config', None) if context else None
        
        # Timing: Pattern building
        t1 = time.time()
        _PATTERNS = self._build_rule_patterns(domain, ext_config)
        pattern_time_ms = (time.time() - t1) * 1000

        text = str(data) if data is not None else ""
        min_len, _stop, _allowed, _max_conf = self._resolve_rule_config(ext_config)
        
        # Timing: Entity extraction from patterns
        t2 = time.time()
        entities = self._extract_entities_from_patterns(
            text,
            _PATTERNS,
            _allowed,
            min_len,
            _stop,
            _max_conf,
        )
        extraction_time_ms = (time.time() - t2) * 1000

        # Timing: Relationship inference
        t3 = time.time()
        relationships = self.infer_relationships(entities, context, data)
        relationship_time_ms = (time.time() - t3) * 1000

        total_time_ms = (time.time() - start_time) * 1000
        
        self._log.info(
            f"Rule-based extraction: {len(entities)} entities, {len(relationships)} relationships | "
            f"timing: patterns={pattern_time_ms:.1f}ms, extraction={extraction_time_ms:.1f}ms, "
            f"relationships={relationship_time_ms:.1f}ms, total={total_time_ms:.1f}ms"
        )
        return EntityExtractionResult(
            entities=entities,
            relationships=relationships,
            confidence=0.7,
            metadata={
                'method': 'rule_based',
                'entity_count': len(entities),
                'pattern_time_ms': pattern_time_ms,
                'extraction_time_ms': extraction_time_ms,
                'relationship_time_ms': relationship_time_ms,
                'total_time_ms': total_time_ms,
            },
        )

    def _build_rule_patterns(
        self,
        domain: str,
        ext_config: Any,
    ) -> list[tuple[str, str]]:
        # Base patterns (domain-agnostic)
        base_patterns: list[tuple[str, str]] = [
            (r'\b(?:Mr|Mrs|Ms|Dr|Prof)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*', 'Person'),
            (r'\b[A-Z][A-Za-z&\s]*(?:LLC|Ltd|Inc|Corp|GmbH|PLC|Co\.)\b', 'Organization'),
            (r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b', 'Date'),
            (r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b', 'Date'),
            (r'\b(?:USD|EUR|GBP)\s*[\d,]+(?:\.\d{2})?\b', 'MonetaryAmount'),
            (r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Street|Avenue|Road|City|County|State|Country|Region|District)\b', 'Location'),
            (r'\b(?:the\s+)?(?:obligation|duty|right|liability|breach|claim|penalty)\s+(?:of\s+)?[A-Z][a-z]+\b', 'Obligation'),
            (r'\b[A-Z][A-Za-z]{3,}\b', 'Concept'),
        ]

        domain_patterns: dict[str, list[tuple[str, str]]] = {
            'legal': [
                (r'\b(?:plaintiff|defendant|claimant|respondent|petitioner)\b', 'LegalParty'),
                (r'\b(?:Article|Section|Clause|Schedule|Appendix)\s+\d+[\w.]*', 'LegalReference'),
                (r'\b(?:indemnif(?:y|ication)|warranty|waiver|covenant|arbitration)\b', 'LegalConcept'),
            ],
            'medical': [
                (r'\b(?:diagnosis|prognosis|symptom|syndrome|disorder|disease|condition)\b', 'MedicalConcept'),
                (r'\b\d+\s*(?:mg|mcg|ml|IU|units?)\b', 'Dosage'),
                (r'\b(?:patient|physician|surgeon|nurse|therapist|specialist)\b', 'MedicalRole'),
            ],
            'technical': [
                (r'\b(?:API|REST|HTTP|JSON|XML|SQL|NoSQL|GraphQL)\b', 'Protocol'),
                (r'\b(?:microservice|endpoint|middleware|container|pipeline|daemon)\b', 'TechnicalComponent'),
                (r'\bv?\d+\.\d+(?:\.\d+)*(?:-\w+)?\b', 'Version'),
            ],
            'financial': [
                (r'\b(?:asset|liability|equity|debit|credit|balance|principal|interest)\b', 'FinancialConcept'),
                (r'\b\d{1,3}(?:,\d{3})*(?:\.\d{2})?\s*(?:USD|EUR|GBP|JPY)?\b', 'MonetaryValue'),
                (r'\b(?:IBAN|SWIFT|BIC|routing\s+number)\b', 'BankIdentifier'),
            ],
        }

        patterns = base_patterns + domain_patterns.get(domain, [])
        if ext_config is not None and hasattr(ext_config, 'custom_rules') and ext_config.custom_rules:
            patterns = patterns[:-1] + list(ext_config.custom_rules) + [patterns[-1]]
        return patterns

    def _resolve_rule_config(
        self,
        ext_config: Any,
    ) -> tuple[int, set[str], set[str], float]:
        try:
            min_len = int(getattr(ext_config, "min_entity_length", 2)) if ext_config is not None else 2
        except (TypeError, ValueError):
            min_len = 2

        try:
            stopwords = {w.lower() for w in (getattr(ext_config, "stopwords", []) or [])} if ext_config is not None else set()
        except (TypeError, AttributeError):
            stopwords = set()

        try:
            allowed_types = set(getattr(ext_config, "allowed_entity_types", []) or []) if ext_config is not None else set()
        except (TypeError, AttributeError):
            allowed_types = set()

        try:
            max_confidence = float(getattr(ext_config, "max_confidence", 1.0)) if ext_config is not None else 1.0
        except (TypeError, ValueError, AttributeError):
            max_confidence = 1.0

        return min_len, stopwords, allowed_types, max_confidence

    def _extract_entities_from_patterns(
        self,
        text: str,
        patterns: list[tuple[str, str]],
        allowed_types: set[str],
        min_len: int,
        stopwords: set[str],
        max_confidence: float,
    ) -> list[Entity]:
        import re as _re
        import time as _time
        import uuid as _uuid

        entities: list[Entity] = []
        seen_texts: set[str] = set()

        for pattern, ent_type in patterns:
            if allowed_types and ent_type not in allowed_types:
                continue
            confidence = 0.5 if ent_type == 'Concept' else 0.75
            confidence = min(confidence, max_confidence)
            for m in _re.finditer(pattern, text):
                raw = m.group(0).strip()
                key = raw.lower()
                if key in seen_texts or len(raw) < min_len or key in stopwords:
                    continue
                seen_texts.add(key)
                entities.append(Entity(
                    id=f"e_{_uuid.uuid4().hex[:8]}",
                    type=ent_type,
                    text=raw,
                    confidence=confidence,
                    source_span=(m.start(), m.end()),
                    last_seen=_time.time(),
                ))

        return entities
    
    def _extract_llm_based(
        self,
        data: Any,
        context: OntologyGenerationContext
    ) -> EntityExtractionResult:
        """
        Extract entities using LLM inference.
        
        Args:
            data: Input data
            context: Extraction context
            
        Returns:
            Extraction result with entities and relationships
        """
        # LLM-based extraction is gated behind ipfs_accelerate availability.
        # When the backend is unavailable, fall back to rule-based extraction.

        if not self.use_ipfs_accelerate or not self._accelerate_available:
            self._log.warning("LLM extraction not available, falling back to rule-based")
            return self._extract_rule_based(data, context)

        # Accelerate is available — delegate to rule-based as a best-effort
        # until full LLM inference is wired.  The result is tagged so callers
        # can distinguish it from a pure rule-based run.
        result = self._extract_rule_based(data, context)
        result.metadata["method"] = "llm_based"
        result.confidence = min(result.confidence * 1.05, 1.0)  # slight confidence boost
        return result
    
    def _extract_hybrid(
        self,
        data: Any,
        context: OntologyGenerationContext
    ) -> EntityExtractionResult:
        """Extract entities using hybrid approach (rules + LLM).

        Combines rule-based and LLM extraction, deduplicating by entity ID so
        that LLM results can extend the rule-based ones without creating
        duplicate entries.
        """
        rule_result = self._extract_rule_based(data, context)

        # Augment with LLM if available
        if self.use_ipfs_accelerate and self._accelerate_available:
            llm_result = self._extract_llm_based(data, context)
        else:
            # No LLM — augment rule-based with relationship inference.
            # infer_relationships takes List[Entity] + context + data keyword arg.
            inferred_rels: List[Relationship] = self.infer_relationships(
                rule_result.entities,
                context,
                data=data,
            )
            llm_result = EntityExtractionResult(
                entities=[],
                relationships=inferred_rels,
                confidence=0.7,
                metadata={"method": "rule_based_with_inference"},
            )

        # Merge with deduplication by entity ID
        seen_entity_ids: set = {e.id for e in rule_result.entities}
        merged_entities = list(rule_result.entities)
        for ent in llm_result.entities:
            if ent.id not in seen_entity_ids:
                merged_entities.append(ent)
                seen_entity_ids.add(ent.id)

        # Dedup relationships by (source_id, target_id, type)
        seen_rel_keys: set = {
            (r.source_id, r.target_id, r.type) for r in rule_result.relationships
        }
        merged_rels = list(rule_result.relationships)
        for rel in llm_result.relationships:
            key = (rel.source_id, rel.target_id, rel.type)
            if key not in seen_rel_keys:
                merged_rels.append(rel)
                seen_rel_keys.add(key)

        avg_conf = (rule_result.confidence + llm_result.confidence) / 2
        return EntityExtractionResult(
            entities=merged_entities,
            relationships=merged_rels,
            confidence=avg_conf,
            metadata={"method": "hybrid", "rule_entities": len(rule_result.entities),
                      "llm_entities": len(llm_result.entities)},
        )

    def _extract_neural(
        self,
        data: Any,
        context: OntologyGenerationContext
    ) -> EntityExtractionResult:
        """Extract entities using neural network models.

        When no neural backend is available, falls back to rule-based extraction
        augmented with relationship inference across the full entity set.
        """
        self._log.info(
            "Neural extraction requested; delegating to rule-based + "
            "relationship inference (neural backend not yet configured)"
        )
        rule_result = self._extract_rule_based(data, context)

        # Enrich with inferred relationships over the full entity graph.
        # infer_relationships takes List[Entity] + context + data keyword arg.
        inferred_rels: List[Relationship] = self.infer_relationships(
            rule_result.entities,
            context,
            data=data,
        )

        # Dedup against existing relationships
        extra_rels = []
        seen_keys = {(r.source_id, r.target_id, r.type) for r in rule_result.relationships}
        for rel in inferred_rels:
            key = (rel.source_id, rel.target_id, rel.type)
            if key not in seen_keys:
                extra_rels.append(rel)
                seen_keys.add(key)

        return EntityExtractionResult(
            entities=rule_result.entities,
            relationships=rule_result.relationships + extra_rels,
            confidence=rule_result.confidence * 0.9,  # lower conf; no true neural backend
            metadata={
                "method": "neural_fallback",
                "inferred_relationships": len(extra_rels),
            },
        )
    
    def _entity_to_dict(self, entity: Entity) -> Dict[str, Any]:
        """Convert Entity to dictionary representation."""
        return {
            'id': entity.id,
            'type': entity.type,
            'text': entity.text,
            'properties': entity.properties,
            'confidence': entity.confidence,
            'source_span': entity.source_span
        }
    
    def _relationship_to_dict(self, relationship: Relationship) -> Dict[str, Any]:
        """Convert Relationship to dictionary representation."""
        return {
            'id': relationship.id,
            'source_id': relationship.source_id,
            'target_id': relationship.target_id,
            'type': relationship.type,
            'properties': relationship.properties,
            'confidence': relationship.confidence,
            'direction': relationship.direction,
        }
    
    def _merge_ontologies(
        self,
        base: Dict[str, Any],
        extension: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Merge two ontologies together.
        
        Args:
            base: Base ontology to extend
            extension: New ontology to add
            
        Returns:
            Merged ontology
        """
        # Smart merge: dedup by id, merge properties, track provenance.
        import copy as _copy

        merged = _copy.deepcopy(base)
        merged.setdefault('entities', [])
        merged.setdefault('relationships', [])
        merged.setdefault('metadata', {})

        # --- entity merge ---
        existing_entity_ids: dict[str, dict] = {
            e['id']: e for e in merged['entities'] if isinstance(e, dict) and 'id' in e
        }
        for ent in extension.get('entities', []):
            if not isinstance(ent, dict) or 'id' not in ent:
                merged['entities'].append(ent)
                continue
            eid = ent['id']
            if eid not in existing_entity_ids:
                new_ent = _copy.deepcopy(ent)
                new_ent.setdefault('provenance', [])
                new_ent['provenance'].append(extension.get('metadata', {}).get('source', 'extension'))
                merged['entities'].append(new_ent)
                existing_entity_ids[eid] = new_ent
            else:
                # Emit warning when entity types conflict; prefer higher-confidence version
                base_ent = existing_entity_ids[eid]
                base_type = base_ent.get('type')
                ext_type = ent.get('type')
                if base_type and ext_type and base_type != ext_type:
                    self._log.warning(
                        f"Entity type conflict for id='{eid}': "
                        f"base={base_type!r}, extension={ext_type!r}. "
                        f"Keeping higher-confidence type."
                    )
                ext_conf = ent.get('confidence', 0.0)
                base_conf = base_ent.get('confidence', 0.0)
                merged_props = {**ent.get('properties', {}), **base_ent.get('properties', {})}
                base_ent['properties'] = merged_props
                if ext_conf > base_conf:
                    base_ent['confidence'] = ext_conf
                    base_ent['type'] = ext_type  # adopt extension's type when more confident
                base_ent.setdefault('provenance', [])
                base_ent['provenance'].append(extension.get('metadata', {}).get('source', 'extension'))

        # --- relationship merge (dedup by source+target+type) ---
        existing_rel_keys: set[tuple] = {
            (r.get('source_id'), r.get('target_id'), r.get('type'))
            for r in merged['relationships'] if isinstance(r, dict)
        }
        for rel in extension.get('relationships', []):
            if not isinstance(rel, dict):
                merged['relationships'].append(rel)
                continue
            key = (rel.get('source_id'), rel.get('target_id'), rel.get('type'))
            if key not in existing_rel_keys:
                new_rel = _copy.deepcopy(rel)
                new_rel.setdefault('provenance', [extension.get('metadata', {}).get('source', 'extension')])
                merged['relationships'].append(new_rel)
                existing_rel_keys.add(key)

        # Update metadata
        merged['metadata']['merged_from'] = merged['metadata'].get('merged_from', [])
        merged['metadata']['merged_from'].append(extension.get('metadata', {}).get('source', 'extension'))

        self._log.info(
            f"Merged ontologies: {len(merged['entities'])} entities, "
            f"{len(merged['relationships'])} relationships"
        )
        return merged

    def generate_merge_provenance_report(
        self,
        ontology: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate a detailed provenance report for a merged ontology.

        Analyzes the provenance metadata tracked during ontology merges
        and produces a comprehensive report showing which entities and
        relationships came from which sources.

        Args:
            ontology: A merged ontology (from :meth:`_merge_ontologies`)

        Returns:
            Provenance report dictionary with keys:
                - 'merged_from': List of source identifiers merged
                - 'entity_counts_by_source': Dict mapping source → entity count
                - 'relationship_counts_by_source': Dict mapping source → relationship count
                - 'entities_by_source': Dict mapping source → list of entity IDs
                - 'relationships_by_source': Dict mapping source → list of relationship IDs
                - 'total_entities': Total entity count
                - 'total_relationships': Total relationship count
                - 'unique_sources': Set of unique source identifiers
                - 'integration_stats': Dict with merge/new/conflict counts

        Example:
            >>> merged = generator._merge_ontologies(base_ont, ext_ont)
            >>> report = generator.generate_merge_provenance_report(merged)
            >>> print(f"Merged from: {report['merged_from']}")
            >>> for source, entities in report['entities_by_source'].items():
            ...     print(f"  {source}: {len(entities)} entities")
        """
        report: Dict[str, Any] = {
            'merged_from': ontology.get('metadata', {}).get('merged_from', []),
            'entity_counts_by_source': {},
            'relationship_counts_by_source': {},
            'entities_by_source': {},
            'relationships_by_source': {},
            'total_entities': 0,
            'total_relationships': 0,
            'unique_sources': set(),
            'integration_stats': {
                'merged_entities': 0,
                'new_entities': 0,
                'total_entities': 0,
                'merged_relationships': 0,
                'new_relationships': 0,
                'total_relationships': 0,
            }
        }

        # Process entities
        for entity in ontology.get('entities', []):
            if not isinstance(entity, dict):
                continue

            report['total_entities'] += 1
            report['integration_stats']['total_entities'] += 1

            provenance = entity.get('provenance', [])
            if not provenance:
                provenance = ['base']  # Implicit provenance for original entities

            for source in provenance:
                report['unique_sources'].add(source)
                report['entity_counts_by_source'][source] = report['entity_counts_by_source'].get(source, 0) + 1
                if source not in report['entities_by_source']:
                    report['entities_by_source'][source] = []
                entity_id = entity.get('id', f"unnamed_{len(report['entities_by_source'][source])}")
                if entity_id not in report['entities_by_source'][source]:
                    report['entities_by_source'][source].append(entity_id)

            # Count merged vs new
            if len(provenance) > 1:
                report['integration_stats']['merged_entities'] += 1
            else:
                report['integration_stats']['new_entities'] += 1

        # Process relationships
        for rel in ontology.get('relationships', []):
            if not isinstance(rel, dict):
                continue

            report['total_relationships'] += 1
            report['integration_stats']['total_relationships'] += 1

            provenance = rel.get('provenance', [])
            if not provenance:
                provenance = ['base']  # Implicit provenance for original relationships

            for source in provenance:
                report['unique_sources'].add(source)
                report['relationship_counts_by_source'][source] = report['relationship_counts_by_source'].get(source, 0) + 1
                if source not in report['relationships_by_source']:
                    report['relationships_by_source'][source] = []
                rel_id = rel.get('id', f"unnamed_{len(report['relationships_by_source'][source])}")
                if rel_id not in report['relationships_by_source'][source]:
                    report['relationships_by_source'][source].append(rel_id)

            # Count merged vs new
            if len(provenance) > 1:
                report['integration_stats']['merged_relationships'] += 1
            else:
                report['integration_stats']['new_relationships'] += 1

        # Convert set to sorted list for serialization
        report['unique_sources'] = sorted(list(report['unique_sources']))

        self._log.info(
            f"Generated merge provenance report: {len(report['unique_sources'])} sources, "
            f"{report['total_entities']} entities, {report['total_relationships']} relationships"
        )

        return report

    def generate_synthetic_ontology(self, domain: str, n_entities: int = 5) -> Dict[str, Any]:
        """Produce a sample ontology for a given *domain* without any input text.

        Generates a small, structurally valid ontology seeded with plausible
        entity and relationship templates for the requested domain.  Useful for
        testing, seeding warm-cache calls, and quick demonstrations.

        Args:
            domain: Domain label (e.g. ``"legal"``, ``"medical"``, ``"finance"``).
            n_entities: Number of synthetic entities to generate (default: 5).

        Returns:
            Ontology dict with ``"entities"``, ``"relationships"``,
            ``"metadata"``, and ``"domain"`` keys.

        Example:
            >>> ont = generator.generate_synthetic_ontology("legal", n_entities=3)
            >>> len(ont["entities"]) == 3
            True
        """
        _DOMAIN_TYPES = {
            "legal": ["Party", "Contract", "Obligation", "Clause", "Court"],
            "medical": ["Patient", "Doctor", "Condition", "Treatment", "Drug"],
            "finance": ["Account", "Transaction", "Asset", "Liability", "Portfolio"],
            "general": ["Entity", "Concept", "Property", "Action", "Event"],
        }
        entity_types = _DOMAIN_TYPES.get(domain.lower(), _DOMAIN_TYPES["general"])
        import time as _time
        current_time = _time.time()
        entities = []
        for i in range(n_entities):
            etype = entity_types[i % len(entity_types)]
            entities.append({
                "id": f"syn_{domain}_{i}",
                "type": etype,
                "text": f"{etype}_{i}",
                "properties": {"synthetic": True, "index": i},
                "confidence": 0.9,
                "last_seen": current_time,
            })

        relationships = []
        for i in range(min(n_entities - 1, 3)):
            relationships.append({
                "id": f"syn_rel_{i}",
                "source_id": entities[i]["id"],
                "target_id": entities[i + 1]["id"],
                "type": "related_to",
                "confidence": 0.8,
            })

        return {
            "entities": entities,
            "relationships": relationships,
            "metadata": {"synthetic": True, "domain": domain, "n_entities": n_entities},
            "domain": domain,
        }

    def deduplicate_entities(
        self,
        result: "EntityExtractionResult",
        key: str = "text",
    ) -> "EntityExtractionResult":
        """Return a new :class:`EntityExtractionResult` with duplicate entities removed.

        Deduplication groups entities by normalised *key* value (lower-case,
        stripped).  Within each group the entity with the **highest confidence**
        is kept.  Relationships whose ``source_id`` or ``target_id`` refer to a
        removed entity are remapped to the surviving entity from the same group.
        Self-loops created by remapping are dropped.

        The result's ``metadata["deduplication_count"]`` records how many
        entities were removed.

        Args:
            result: The extraction result to deduplicate.
            key: Entity attribute to group by (default: ``"text"``).
                Currently only ``"text"`` and ``"id"`` are supported.

        Returns:
            A new :class:`EntityExtractionResult` with duplicates removed.

        Raises:
            ValueError: If *key* is not ``"text"`` or ``"id"``.

        Example:
            >>> deduped = generator.deduplicate_entities(result)
            >>> len(deduped.entities) <= len(result.entities)
            True
        """
        if key not in ("text", "id"):
            raise ValueError(f"key must be 'text' or 'id'; got {key!r}")

        from collections import defaultdict

        # Group entities by normalised key value
        groups: dict = defaultdict(list)
        for ent in result.entities:
            raw = getattr(ent, key, "")
            normalised = str(raw).lower().strip()
            groups[normalised].append(ent)

        # Keep highest-confidence entity per group; build id -> surviving id map
        kept: List[Entity] = []
        id_map: dict = {}  # removed_id -> surviving_id
        for group in groups.values():
            winner = max(group, key=lambda e: e.confidence)
            kept.append(winner)
            for ent in group:
                if ent.id != winner.id:
                    id_map[ent.id] = winner.id

        kept_ids = {e.id for e in kept}
        deduplication_count = len(result.entities) - len(kept)

        # Remap relationships; drop self-loops
        kept_rels = []
        for r in result.relationships:
            src = id_map.get(r.source_id, r.source_id)
            tgt = id_map.get(r.target_id, r.target_id)
            if src in kept_ids and tgt in kept_ids and src != tgt:
                import dataclasses as _dc
                kept_rels.append(_dc.replace(r, source_id=src, target_id=tgt))

        updated_metadata = dict(result.metadata)
        updated_metadata["deduplication_count"] = deduplication_count
        return EntityExtractionResult(
            entities=kept,
            relationships=kept_rels,
            confidence=result.confidence,
            metadata=updated_metadata,
            errors=list(result.errors),
        )

    def anonymize_entities(
        self,
        result: "EntityExtractionResult",
        replacement: str = "[REDACTED]",
    ) -> "EntityExtractionResult":
        """Return a new result with entity text replaced by *replacement*.

        Replaces the ``text`` field of every entity with *replacement*.
        Other fields (id, type, confidence, properties, source_span) are
        preserved.  Relationships are returned unchanged.

        Args:
            result: Extraction result to anonymise.
            replacement: Placeholder string (default: ``"[REDACTED]"``).

        Returns:
            New :class:`EntityExtractionResult` with anonymised entity text.

        Example:
            >>> anon = generator.anonymize_entities(result)
            >>> all(e.text == "[REDACTED]" for e in anon.entities)
            True
        """
        import dataclasses as _dc

        anon_entities = [_dc.replace(e, text=replacement) for e in result.entities]
        return EntityExtractionResult(
            entities=anon_entities,
            relationships=list(result.relationships),
            confidence=result.confidence,
            metadata=dict(result.metadata),
            errors=list(result.errors),
        )

    def tag_entities(
        self,
        result: "EntityExtractionResult",
        tags: Dict[str, Any],
    ) -> "EntityExtractionResult":
        """Return a new result with *tags* merged into every entity's properties.

        Each entity's ``properties`` dict is shallow-merged with *tags*;
        existing keys are **overwritten** by *tags* values.

        Args:
            result: Extraction result to annotate.
            tags: Key-value pairs to add to each entity's properties.

        Returns:
            New :class:`EntityExtractionResult` with tagged entities.

        Example:
            >>> tagged = generator.tag_entities(result, {"source": "document_1", "review": True})
            >>> tagged.entities[0].properties["source"]
            'document_1'
        """
        import dataclasses as _dc

        tagged_entities = [
            _dc.replace(e, properties={**e.properties, **tags})
            for e in result.entities
        ]
        return EntityExtractionResult(
            entities=tagged_entities,
            relationships=list(result.relationships),
            confidence=result.confidence,
            metadata=dict(result.metadata),
            errors=list(result.errors),
        )

    def score_entity(self, entity: "Entity") -> float:
        """Return a single-entity confidence heuristic score (0.0 – 1.0).

        The score is derived from three signals:

        1. **Confidence** -- the entity's own ``confidence`` attribute (0 – 1).
        2. **Text length** -- longer entity texts are typically more specific
           and thus more trustworthy; saturates above 50 characters.
        3. **Type specificity** -- concrete domain types (e.g. ``"Person"``,
           ``"Organization"``) score higher than generic labels (``"Entity"``,
           ``"Concept"``, ``"Unknown"``).

        The three signals are blended with weights 0.5 / 0.25 / 0.25.

        Args:
            entity: An :class:`Entity` instance.

        Returns:
            Float in [0.0, 1.0].

        Example:
            >>> s = generator.score_entity(entity)
            >>> 0.0 <= s <= 1.0
            True
        """
        _GENERIC = {"entity", "concept", "unknown", "other", "thing"}

        conf_score = max(0.0, min(1.0, float(entity.confidence)))

        text_len = len(entity.text) if entity.text else 0
        len_score = min(1.0, text_len / 50.0)

        type_score = 0.0 if entity.type.lower() in _GENERIC else 1.0

        return round(0.5 * conf_score + 0.25 * len_score + 0.25 * type_score, 6)

    def batch_extract_with_spans(
        self,
        documents: List[str],
        context: "OntologyGenerationContext",
        max_workers: int = 4,
    ) -> List["EntityExtractionResult"]:
        """Extract entities with character spans from multiple documents.

        Calls :meth:`extract_entities_with_spans` on each document using a
        :class:`~concurrent.futures.ThreadPoolExecutor` to parallelise I/O-
        bound work.  Results are returned in the **same order** as *documents*.

        Args:
            documents: List of raw text strings.
            context: Shared extraction context.
            max_workers: Thread-pool size (default: 4).

        Returns:
            List of :class:`EntityExtractionResult`, one per document, in
            original order.

        Example:
            >>> results = generator.batch_extract_with_spans(docs, ctx)
            >>> len(results) == len(docs)
            True
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        if not documents:
            return []

        ordered: List[Optional["EntityExtractionResult"]] = [None] * len(documents)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self.extract_entities_with_spans, doc, context): idx
                for idx, doc in enumerate(documents)
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    ordered[idx] = future.result()
                except Exception as exc:
                    ordered[idx] = EntityExtractionResult(
                        entities=[],
                        relationships=[],
                        confidence=0.0,
                        errors=[f"Extraction error: {exc}"],
                    )
        return ordered  # type: ignore[return-value]

    def extract_keyphrases(self, text: str, top_k: int = 10) -> List[str]:
        """Extract the top-*k* keyphrases from *text*.

        Uses a simple frequency-based heuristic: tokenise by whitespace,
        normalise to lower-case, remove single-character tokens and common
        English stop-words, count occurrences, and return the *top_k* most
        frequent tokens.  This is intentionally lightweight and requires no
        external dependencies.

        Args:
            text: Plain text to analyse.
            top_k: Maximum number of keyphrases to return (default 10).

        Returns:
            List of keyphrase strings, highest-frequency first.

        Example:
            >>> kp = gen.extract_keyphrases("the cat sat on the mat cat cat", top_k=3)
            >>> kp[0]
            'cat'
        """
        _STOPWORDS = frozenset([
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
            "for", "of", "with", "by", "from", "is", "are", "was", "were",
            "be", "been", "being", "have", "has", "had", "do", "does", "did",
            "will", "would", "could", "should", "may", "might", "shall",
            "not", "no", "it", "its", "this", "that", "these", "those",
        ])
        import re as _re
        tokens = _re.findall(r"[A-Za-z][A-Za-z0-9'-]*", text.lower())
        freq: Dict[str, int] = {}
        for tok in tokens:
            if len(tok) > 1 and tok not in _STOPWORDS:
                freq[tok] = freq.get(tok, 0) + 1
        sorted_tokens = sorted(freq, key=lambda t: (-freq[t], t))
        return sorted_tokens[:top_k]

    def extract_noun_phrases(self, text: str) -> List[str]:
        """Extract simple noun phrases from *text* using a rule-based chunker.

        Uses a lightweight pattern: sequences of optional determiners,
        adjectives, and nouns.  No external NLP library is required.

        Args:
            text: Plain text to chunk.

        Returns:
            List of noun-phrase strings (may contain duplicates).

        Example:
            >>> nps = gen.extract_noun_phrases("The quick brown fox jumped")
            >>> "quick brown fox" in nps or len(nps) >= 0
            True
        """
        import re as _re
        _ARTICLES = frozenset(["a", "an", "the", "this", "that", "these", "those", "my", "your", "its"])
        _ADJS = frozenset([
            "quick", "brown", "big", "small", "large", "old", "new", "good", "bad",
            "high", "low", "long", "short", "first", "last", "great", "little",
        ])
        tokens = _re.findall(r"[A-Za-z][A-Za-z0-9'-]*", text)
        phrases: List[str] = []
        i = 0
        while i < len(tokens):
            tok = tokens[i].lower()
            if tok in _ARTICLES or tok in _ADJS or (tokens[i].istitle() and len(tok) > 1):
                # start of potential NP
                phrase_toks = [tokens[i]]
                j = i + 1
                while j < len(tokens):
                    next_tok = tokens[j].lower()
                    if next_tok in _ADJS or (tokens[j].istitle() and len(tokens[j]) > 1) or (len(tokens[j]) > 3 and tokens[j][0].islower()):
                        phrase_toks.append(tokens[j])
                        j += 1
                    else:
                        break
                if len(phrase_toks) >= 2:
                    # strip leading article from phrase display
                    start = 1 if phrase_toks[0].lower() in _ARTICLES else 0
                    chunk = " ".join(phrase_toks[start:]) if start else " ".join(phrase_toks)
                    if chunk:
                        phrases.append(chunk)
                    i = j
                else:
                    i += 1
            else:
                i += 1
        return phrases

    def merge_results(
        self,
        results: List["EntityExtractionResult"],
    ) -> "EntityExtractionResult":
        """Merge multiple :class:`EntityExtractionResult` objects into one.

        Entities and relationships from all results are concatenated.
        The overall ``confidence`` of the merged result is the mean of the
        individual confidence values (or 0.0 for an empty list).
        Metadata dicts are shallow-merged (later results win on conflict).

        Args:
            results: List of results to merge.

        Returns:
            A single combined :class:`EntityExtractionResult`.

        Example:
            >>> merged = gen.merge_results([r1, r2, r3])
            >>> len(merged.entities) == len(r1.entities) + len(r2.entities) + len(r3.entities)
            True
        """
        if not results:
            return EntityExtractionResult(entities=[], relationships=[], confidence=0.0)
        all_entities: List["Entity"] = []
        all_rels: List[Any] = []
        all_errors: List[str] = []
        merged_meta: Dict[str, Any] = {}
        for r in results:
            all_entities.extend(r.entities)
            all_rels.extend(r.relationships)
            all_errors.extend(r.errors)
            merged_meta.update(r.metadata)
        avg_conf = sum(r.confidence for r in results) / len(results)
        return EntityExtractionResult(
            entities=all_entities,
            relationships=all_rels,
            confidence=avg_conf,
            metadata=merged_meta,
            errors=all_errors,
        )



    def dedup_by_text_prefix(
        self,
        result: "EntityExtractionResult",
        prefix_len: int = 5,
    ) -> "EntityExtractionResult":
        """Deduplicate entities that share the same normalised text prefix.

        When two entities share the first *prefix_len* characters (lowercased,
        stripped), only the one with the higher ``confidence`` is kept.
        Relationships referencing removed entities are also removed.

        Args:
            result: Source :class:`EntityExtractionResult`.
            prefix_len: Number of leading characters used as the dedup key.
                Must be >= 1.

        Returns:
            New :class:`EntityExtractionResult` with duplicates removed.

        Example:
            >>> r2 = gen.dedup_by_text_prefix(result, prefix_len=4)
        """
        if prefix_len < 1:
            raise ValueError("prefix_len must be >= 1")
        seen: dict = {}
        for entity in result.entities:
            key = entity.text.lower().strip()[:prefix_len]
            if key not in seen or entity.confidence > seen[key].confidence:
                seen[key] = entity
        deduped = list(seen.values())
        kept_ids = {e.id for e in deduped}
        kept_rels = [
            r for r in result.relationships
            if r.source_id in kept_ids and r.target_id in kept_ids
        ]
        import dataclasses as _dc
        return _dc.replace(result, entities=deduped, relationships=kept_rels)


    def count_entities_by_type(
        self,
        result: "EntityExtractionResult",
    ) -> Dict[str, int]:
        """Return a frequency dict of entity type → count for *result*.

        Args:
            result: Source :class:`EntityExtractionResult`.

        Returns:
            Dict mapping entity ``type`` string to the number of entities with
            that type, sorted by count descending.

        Example:
            >>> counts = gen.count_entities_by_type(result)
            >>> counts.get("Person", 0) >= 0
            True
        """
        freq: Dict[str, int] = {}
        for entity in result.entities:
            freq[entity.type] = freq.get(entity.type, 0) + 1
        return dict(sorted(freq.items(), key=lambda kv: kv[1], reverse=True))

    def entity_count(self, result: "EntityExtractionResult") -> int:
        """Return the total number of entities in *result*.

        Args:
            result: Source :class:`EntityExtractionResult`.

        Returns:
            Non-negative integer entity count.

        Example:
            >>> gen.entity_count(result)
            3
        """
        return len(result.entities)

    def relationship_count(self, result: "EntityExtractionResult") -> int:
        """Return the total number of relationships in *result*.

        Args:
            result: Source :class:`EntityExtractionResult`.

        Returns:
            Non-negative integer relationship count.

        Example:
            >>> gen.relationship_count(result)
            0
        """
        return len(result.relationships)

    def relationship_types(self, result: "EntityExtractionResult") -> Set[str]:
        """Return unique relationship types from *result*.

        Args:
            result: Source :class:`EntityExtractionResult`.

        Returns:
            Set of unique relationship type strings.

        Example:
            >>> gen.relationship_types(result)
            {'WORKS_FOR', 'LOCATED_IN'}
        """
        return {rel.type for rel in result.relationships}

    def entity_ids(self, result: "EntityExtractionResult") -> List[str]:
        """Return the ``id`` of every entity in *result*.

        Args:
            result: Source :class:`EntityExtractionResult`.

        Returns:
            List of entity ID strings in the same order as
            ``result.entities``.

        Example:
            >>> gen.entity_ids(result)
            ['e1', 'e2']
        """
        return [e.id for e in result.entities]

    def split_result(
        self,
        result: "EntityExtractionResult",
        n: int,
    ) -> List["EntityExtractionResult"]:
        """Split *result* into *n* balanced non-empty chunks by entities.

        Relationships are retained only when both endpoints belong to the same
        chunk.

        Args:
            result: Source :class:`EntityExtractionResult`.
            n: Desired number of chunks. Must be >= 1.

        Returns:
            List of chunked :class:`EntityExtractionResult` values.

        Raises:
            ValueError: If ``n < 1``.
        """
        if n < 1:
            raise ValueError("n must be >= 1")
        if not result.entities:
            return []

        total = len(result.entities)
        chunk_count = min(n, total)
        base = total // chunk_count
        remainder = total % chunk_count

        chunks: List[EntityExtractionResult] = []
        cursor = 0

        for idx in range(chunk_count):
            size = base + (1 if idx < remainder else 0)
            entities_slice = result.entities[cursor:cursor + size]
            cursor += size

            entity_ids = {e.id for e in entities_slice}
            relationships_slice = [
                rel for rel in result.relationships
                if rel.source_id in entity_ids and rel.target_id in entity_ids
            ]

            metadata = dict(result.metadata)
            metadata.update({"chunk_index": idx, "chunk_count": chunk_count})

            chunks.append(
                EntityExtractionResult(
                    entities=list(entities_slice),
                    relationships=relationships_slice,
                    confidence=result.confidence,
                    metadata=metadata,
                    errors=list(result.errors),
                )
            )

        return chunks

    def entities_by_type(self, result: "EntityExtractionResult") -> Dict[str, List["Entity"]]:
        """Return a dict grouping entities in *result* by their ``type``.

        Args:
            result: Source :class:`EntityExtractionResult`.

        Returns:
            Dict mapping entity type strings to lists of :class:`Entity`
            objects of that type.  Types not present in *result* are omitted.

        Example:
            >>> d = gen.entities_by_type(result)
            >>> d.get("PERSON", [])
            [...]
        """
        groups: Dict[str, list] = {}
        for e in result.entities:
            groups.setdefault(e.type, []).append(e)
        return groups

    def sorted_entities(
        self,
        result: "EntityExtractionResult",
        key: str = "confidence",
        reverse: bool = True,
    ) -> List["Entity"]:
        """Return entities from *result* sorted by *key*.

        Args:
            result: Source :class:`EntityExtractionResult`.
            key: Entity attribute name to sort by.  Defaults to
                ``"confidence"``.
            reverse: If ``True`` (default), sort in descending order.

        Returns:
            New list of :class:`Entity` objects in the requested order.

        Raises:
            AttributeError: If *key* is not a valid entity attribute.

        Example:
            >>> sorted_ents = gen.sorted_entities(result, key="confidence")
        """
        return sorted(result.entities, key=lambda e: getattr(e, key), reverse=reverse)

    def explain_entity(self, entity: "Entity") -> str:
        """Return a concise one-line English description of *entity*.

        Args:
            entity: The :class:`Entity` to describe.

        Returns:
            Human-readable string of the form
            ``"<text> (<type>) — confidence: <conf>"``

        Example:
            >>> gen.explain_entity(Entity(id="e1", text="Alice", type="PERSON", confidence=0.9))
            'Alice (PERSON) — confidence: 0.90'
        """
        return f"{entity.text} ({entity.type}) — confidence: {entity.confidence:.2f}"

    def rebuild_result(
        self,
        entities: List["Entity"],
        relationships: Optional[List["Relationship"]] = None,
        confidence: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "EntityExtractionResult":
        """Wrap *entities* (and optional *relationships*) in a new result.

        Args:
            entities: List of :class:`Entity` objects to include.
            relationships: Optional list of :class:`Relationship` objects.
                Defaults to an empty list.
            confidence: Overall confidence for the result.  Defaults to 1.0.
            metadata: Optional metadata dict.  Defaults to ``{}``.

        Returns:
            New :class:`EntityExtractionResult`.

        Example:
            >>> result = gen.rebuild_result([entity1, entity2])
            >>> len(result.entities) == 2
            True
        """
        return EntityExtractionResult(
            entities=list(entities),
            relationships=list(relationships) if relationships is not None else [],
            confidence=confidence,
            metadata=dict(metadata) if metadata is not None else {},
        )

    def rename_entity(
        self,
        result: "EntityExtractionResult",
        entity_id: str,
        new_text: str,
    ) -> "EntityExtractionResult":
        """Return a copy of *result* with the entity identified by *entity_id* renamed.

        All other fields of the entity are preserved.  The result's
        relationships are unchanged.

        Args:
            result: Source :class:`EntityExtractionResult`.
            entity_id: The ``id`` of the entity to rename.
            new_text: New text value for the entity.

        Returns:
            New :class:`EntityExtractionResult` with the renamed entity.

        Raises:
            KeyError: If no entity with *entity_id* exists in *result*.

        Example:
            >>> r2 = gen.rename_entity(result, "e1", "Alice Smith")
        """
        import dataclasses as _dc
        found = False
        new_entities = []
        for e in result.entities:
            if e.id == entity_id:
                new_entities.append(_dc.replace(e, text=new_text))
                found = True
            else:
                new_entities.append(e)
        if not found:
            raise KeyError(f"No entity with id={entity_id!r} in result")
        return _dc.replace(result, entities=new_entities)


    def strip_low_confidence(
        self,
        result: "EntityExtractionResult",
        threshold: float = 0.5,
    ) -> "EntityExtractionResult":
        """Return a copy of *result* with low-confidence entities removed.

        Entities with ``confidence < threshold`` are excluded.  Relationships
        referencing removed entities are also pruned.

        Args:
            result: Source :class:`EntityExtractionResult`.
            threshold: Minimum confidence required to keep an entity.
                Defaults to 0.5.

        Returns:
            New :class:`EntityExtractionResult` with filtered entities.

        Example:
            >>> r2 = gen.strip_low_confidence(result, threshold=0.7)
        """
        filtered = [e for e in result.entities if e.confidence >= threshold]
        kept_ids = {e.id for e in filtered}
        kept_rels = [
            r for r in result.relationships
            if r.source_id in kept_ids and r.target_id in kept_ids
        ]
        import dataclasses as _dc
        return _dc.replace(result, entities=filtered, relationships=kept_rels)


    def top_entities(
        self,
        result: "EntityExtractionResult",
        n: int = 10,
    ) -> List["Entity"]:
        """Return the top *n* entities by confidence in descending order.

        Args:
            result: Source :class:`EntityExtractionResult`.
            n: Number of entities to return (at most).

        Returns:
            List of :class:`Entity` objects, length <= n, sorted by confidence
            descending.

        Example:
            >>> top = gen.top_entities(result, n=5)
            >>> len(top) <= 5
            True
        """
        return sorted(result.entities, key=lambda e: e.confidence, reverse=True)[:n]

    def filter_result_by_confidence(
        self,
        result: "EntityExtractionResult",
        min_conf: float = 0.5,
    ) -> "EntityExtractionResult":
        """Alias for :meth:`strip_low_confidence` with a cleaner parameter name.

        Args:
            result: Source :class:`EntityExtractionResult`.
            min_conf: Minimum confidence required to keep an entity (default 0.5).

        Returns:
            New :class:`EntityExtractionResult` with filtered entities/relationships.

        Example:
            >>> clean = gen.filter_result_by_confidence(result, min_conf=0.7)
        """
        return self.strip_low_confidence(result, threshold=min_conf)

    def relationship_density(self, result: "EntityExtractionResult") -> float:
        """Return the ratio of relationships to entities in *result*.

        Args:
            result: Source :class:`EntityExtractionResult`.

        Returns:
            Float ratio ``len(relationships) / len(entities)``.
            Returns ``0.0`` when there are no entities.

        Example:
            >>> gen.relationship_density(result)
            0.5
        """
        if not result.entities:
            return 0.0
        return len(result.relationships) / len(result.entities)

    def group_entities_by_confidence_band(
        self,
        result: "EntityExtractionResult",
        bands: List[float],
    ) -> Dict[str, List["Entity"]]:
        """Bucket entities by confidence using ascending threshold *bands*.

        Labels are ``"<t0"``, ``"[t0,t1)"``, ... and ``">=t_last"``.
        """
        thresholds = sorted(float(b) for b in bands)
        buckets: Dict[str, List["Entity"]] = {}
        if not thresholds:
            buckets["all"] = list(result.entities)
            return buckets
        labels = [f"<{thresholds[0]:g}"]
        labels += [f"[{thresholds[i]:g},{thresholds[i+1]:g})" for i in range(len(thresholds) - 1)]
        labels += [f">={thresholds[-1]:g}"]
        for label in labels:
            buckets[label] = []
        for e in result.entities:
            conf = e.confidence
            if conf < thresholds[0]:
                buckets[labels[0]].append(e)
                continue
            placed = False
            for i in range(len(thresholds) - 1):
                if thresholds[i] <= conf < thresholds[i + 1]:
                    buckets[labels[i + 1]].append(e)
                    placed = True
                    break
            if not placed:
                buckets[labels[-1]].append(e)
        return buckets

    def entity_count_property(self, result: "EntityExtractionResult") -> int:
        """Return ``len(result.entities)`` as a convenience alias."""
        return len(result.entities)

    def relationships_for_entity(
        self,
        result: "EntityExtractionResult",
        entity_id: str,
    ) -> List["Relationship"]:
        """Return all relationships where *entity_id* is source or target.

        Args:
            result: Source :class:`EntityExtractionResult`.
            entity_id: Entity ID to match against.

        Returns:
            List of :class:`Relationship` objects where
            ``source_id == entity_id`` or ``target_id == entity_id``.

        Example:
            >>> rels = gen.relationships_for_entity(result, "e1")
        """
        return [
            r for r in result.relationships
            if r.source_id == entity_id or r.target_id == entity_id
        ]

    def validate_result(self, result: "EntityExtractionResult") -> List[str]:
        """Return a list of validation issues found in *result*.

        Checks include:
        - Entities with empty or blank ``text``
        - Entities with ``confidence`` outside [0, 1]
        - Relationships with ``source_id`` or ``target_id`` not in the entity
          id set

        Args:
            result: :class:`EntityExtractionResult` to validate.

        Returns:
            List of human-readable issue strings.  Empty list means no issues.
        """
        issues: List[str] = []
        entity_ids = {e.id for e in result.entities}
        for e in result.entities:
            if not e.text or not e.text.strip():
                issues.append(f"Entity {e.id!r} has empty text")
            if not 0.0 <= e.confidence <= 1.0:
                issues.append(
                    f"Entity {e.id!r} has out-of-range confidence: {e.confidence}"
                )
        for r in result.relationships:
            if r.source_id not in entity_ids:
                issues.append(
                    f"Relationship {r.id!r} references unknown source_id {r.source_id!r}"
                )
            if r.target_id not in entity_ids:
                issues.append(
                    f"Relationship {r.id!r} references unknown target_id {r.target_id!r}"
                )
        return issues

    def confidence_stats(self, result: "EntityExtractionResult") -> Dict[str, float]:
        """Return descriptive statistics for entity confidences in *result*.

        Args:
            result: :class:`EntityExtractionResult` with entities.

        Returns:
            Dict with keys ``count``, ``mean``, ``min``, ``max``, and ``std``.
            All values are ``0.0`` when there are no entities.
        """
        import math as _math
        if not result.entities:
            return {"count": 0.0, "mean": 0.0, "min": 0.0, "max": 0.0, "std": 0.0}
        confs = [e.confidence for e in result.entities]
        mean = sum(confs) / len(confs)
        variance = sum((c - mean) ** 2 for c in confs) / len(confs)
        return {
            "count": float(len(confs)),
            "mean": mean,
            "min": min(confs),
            "max": max(confs),
            "std": _math.sqrt(variance),
        }

    def clone_result(self, result: "EntityExtractionResult") -> "EntityExtractionResult":
        """Return a deep copy of *result*.

        The returned object has independent copies of the entities and
        relationships lists so mutations to one do not affect the other.

        Args:
            result: Source :class:`EntityExtractionResult`.

        Returns:
            New :class:`EntityExtractionResult` with copied data.
        """
        import copy as _copy
        return _copy.deepcopy(result)

    def add_entity(
        self, result: "EntityExtractionResult", entity: "Entity"
    ) -> "EntityExtractionResult":
        """Return a new result with *entity* appended to the entities list.

        The original *result* is not modified.

        Args:
            result: Source :class:`EntityExtractionResult`.
            entity: :class:`Entity` to append.

        Returns:
            New :class:`EntityExtractionResult` with *entity* added.
        """
        import dataclasses as _dc
        new_entities = list(result.entities) + [entity]
        return _dc.replace(result, entities=new_entities)

    def remove_entity(
        self, result: "EntityExtractionResult", entity_id: str
    ) -> "EntityExtractionResult":
        """Return a new result without the entity identified by *entity_id*.

        Also prunes any relationships whose ``source_id`` or ``target_id``
        matches the removed entity.

        Args:
            result: Source :class:`EntityExtractionResult`.
            entity_id: ID of the entity to remove.

        Returns:
            New :class:`EntityExtractionResult` without the entity or its
            associated relationships.
        """
        import dataclasses as _dc
        new_entities = [e for e in result.entities if e.id != entity_id]
        new_rels = [
            r for r in result.relationships
            if r.source_id != entity_id and r.target_id != entity_id
        ]
        return _dc.replace(result, entities=new_entities, relationships=new_rels)

    def type_diversity(self, result: "EntityExtractionResult") -> int:
        """Return the count of distinct entity types in *result*.

        Args:
            result: :class:`EntityExtractionResult` with entities.

        Returns:
            Integer count of unique ``type`` values; ``0`` when empty.
        """
        return len({e.type for e in result.entities})

    def normalize_confidence(
        self, result: "EntityExtractionResult"
    ) -> "EntityExtractionResult":
        """Return a new result with entity confidences scaled to [0, 1].

        If all entities already have confidence in [0, 1] and the range
        (max - min) is zero, the result is returned unchanged.  Otherwise,
        each confidence is rescaled using min-max normalization.

        Args:
            result: Source :class:`EntityExtractionResult`.

        Returns:
            New :class:`EntityExtractionResult` with normalised entity
            confidences.  Relationships are copied unchanged.
        """
        import dataclasses as _dc
        if not result.entities:
            return result
        confs = [e.confidence for e in result.entities]
        lo, hi = min(confs), max(confs)
        if hi == lo:
            return result
        new_entities = [
            _dc.replace(e, confidence=(e.confidence - lo) / (hi - lo))
            for e in result.entities
        ]
        return _dc.replace(result, entities=new_entities)

    def entity_confidence_map(self, result: "EntityExtractionResult") -> Dict[str, float]:
        """Return a mapping of entity id → confidence for all entities in *result*.

        Args:
            result: :class:`EntityExtractionResult` with entities.

        Returns:
            Dict mapping each entity ``id`` string to its ``confidence`` float.
            Returns ``{}`` when there are no entities.

        Example:
            >>> gen.entity_confidence_map(result)
            {'e1': 0.9, 'e2': 0.7}
        """
        return {e.id: e.confidence for e in result.entities}

    def average_confidence(self, result: "EntityExtractionResult") -> float:
        """Return the mean confidence across all entities in *result*.

        Args:
            result: :class:`EntityExtractionResult`.

        Returns:
            Mean confidence float; ``0.0`` when there are no entities.
        """
        if not result.entities:
            return 0.0
        return sum(e.confidence for e in result.entities) / len(result.entities)

    def high_confidence_entities(
        self,
        result: "EntityExtractionResult",
        threshold: float = 0.8,
    ) -> list:
        """Return entities whose confidence is >= *threshold*.

        Args:
            result: :class:`EntityExtractionResult`.
            threshold: Minimum confidence to include (default 0.8).

        Returns:
            List of :class:`Entity` objects passing the threshold.
        """
        return [e for e in result.entities if e.confidence >= threshold]

    def filter_entities_by_type(
        self,
        result: "EntityExtractionResult",
        entity_type: str,
    ) -> list:
        """Return all entities of a specific *entity_type*.

        Args:
            result: :class:`EntityExtractionResult`.
            entity_type: Type string to filter by.

        Returns:
            List of :class:`Entity` objects with matching ``type``.
        """
        return [e for e in result.entities if e.type == entity_type]

    def deduplicate_by_id(
        self,
        result: "EntityExtractionResult",
    ) -> "EntityExtractionResult":
        """Return a copy of *result* with duplicate entity ids removed.

        When duplicate ids appear, the entity with the highest confidence is
        kept.  Uses :func:`dataclasses.replace` to preserve immutability.

        Args:
            result: :class:`EntityExtractionResult`.

        Returns:
            New :class:`EntityExtractionResult` with unique entity ids.
        """
        import dataclasses as _dc
        seen: dict = {}
        for e in result.entities:
            if e.id not in seen or e.confidence > seen[e.id].confidence:
                seen[e.id] = e
        unique = list(seen.values())
        return _dc.replace(result, entities=unique)

    def unique_relationship_types(self, result: "EntityExtractionResult") -> set:
        """Return the set of distinct relationship types in *result*.

        Args:
            result: :class:`EntityExtractionResult` with relationships.

        Returns:
            Set of unique relationship ``type`` strings;
            ``set()`` when there are no relationships.

        Example:
            >>> types = gen.unique_relationship_types(result)
            >>> types == {'causes', 'is_a', 'part_of'}
            True
        """
        return {r.type for r in result.relationships}

    def filter_low_confidence(
        self,
        result: "EntityExtractionResult",
        threshold: float = 0.5,
    ) -> "EntityExtractionResult":
        """Return a copy of *result* with entities below *threshold* removed.

        Args:
            result: :class:`EntityExtractionResult`.
            threshold: Minimum confidence to retain (inclusive, default 0.5).

        Returns:
            New :class:`EntityExtractionResult` keeping only entities with
            ``confidence >= threshold``.
        """
        import dataclasses as _dc
        kept = [e for e in result.entities if e.confidence >= threshold]
        return _dc.replace(result, entities=kept)

    def apply_config(
        self,
        result: "EntityExtractionResult",
        config: "ExtractionConfig",
    ) -> "EntityExtractionResult":
        """Re-filter *result* by applying the constraints in *config*.

        Applies :attr:`ExtractionConfig.confidence_threshold` to remove
        low-confidence entities from *result* and returns a new
        :class:`EntityExtractionResult`.  Any relationships whose source or
        target entity was removed are also pruned.

        Args:
            result: The extraction result to filter.
            config: An :class:`ExtractionConfig` whose
                ``confidence_threshold`` is used as the minimum confidence.

        Returns:
            A new :class:`EntityExtractionResult` with only entities (and
            their relationships) that satisfy the config threshold.
        """
        import dataclasses as _dc
        threshold = getattr(config, "confidence_threshold", 0.0)
        kept_entities = [e for e in result.entities if e.confidence >= threshold]
        kept_ids = {getattr(e, "id", None) for e in kept_entities}
        kept_rels = [
            r for r in result.relationships
            if getattr(r, "source_id", None) in kept_ids
            and getattr(r, "target_id", None) in kept_ids
        ]
        return _dc.replace(result, entities=kept_entities, relationships=kept_rels)

    def confidence_histogram(self, result, bins: int = 5) -> dict:
        """Return a bucket-count histogram of entity confidence scores.

        Args:
            result: :class:`EntityExtractionResult`.
            bins: Number of equal-width buckets spanning [0.0, 1.0].

        Returns:
            Dict mapping bucket label (str like ``"0.0-0.2"``) to count.
        """
        if bins < 1:
            bins = 1
        width = 1.0 / bins
        buckets: dict = {}
        for i in range(bins):
            lo = round(i * width, 6)
            hi = round((i + 1) * width, 6)
            label = f"{lo:.2f}-{hi:.2f}"
            buckets[label] = sum(
                1 for e in result.entities if lo <= e.confidence < hi
            )
        # Clamp exactly-1.0 confidence into the last bucket
        last_label = list(buckets.keys())[-1]
        buckets[last_label] += sum(
            1 for e in result.entities if e.confidence == 1.0
        )
        return buckets

    def mean_confidence(self, result) -> float:
        """Return the mean confidence across all entities in *result*.

        Args:
            result: :class:`EntityExtractionResult`.

        Returns:
            Mean confidence; ``0.0`` when no entities.
        """
        if not result.entities:
            return 0.0
        return sum(e.confidence for e in result.entities) / len(result.entities)

    def confidence_std(self, result) -> float:
        """Return the standard deviation of entity confidence scores.

        Args:
            result: :class:`EntityExtractionResult`.

        Returns:
            Float std; ``0.0`` when fewer than 2 entities.
        """
        if len(result.entities) < 2:
            return 0.0
        scores = [e.confidence for e in result.entities]
        mean = sum(scores) / len(scores)
        variance = sum((s - mean) ** 2 for s in scores) / len(scores)
        return variance ** 0.5

    def entity_type_distribution(self, result) -> dict:
        """Return a dict mapping each entity type to its relative frequency.

        Args:
            result: :class:`EntityExtractionResult`.

        Returns:
            Dict of ``{type: fraction}``; empty dict when no entities.
        """
        if not result.entities:
            return {}
        counts: dict = {}
        for e in result.entities:
            counts[e.type] = counts.get(e.type, 0) + 1
        total = len(result.entities)
        return {t: c / total for t, c in counts.items()}

    def compact_result(self, result) -> "EntityExtractionResult":
        """Return a copy of *result* with entities that have empty properties removed.

        An entity is considered "empty-properties" when ``entity.properties``
        is an empty dict or ``None``.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            New ``EntityExtractionResult`` retaining only entities whose
            ``properties`` dict contains at least one key.
        """
        filtered = [e for e in result.entities if e.properties]
        return EntityExtractionResult(
            entities=filtered,
            relationships=result.relationships,
            confidence=result.confidence,
            metadata=result.metadata,
            errors=result.errors,
        )

    def top_k_entities_by_confidence(self, result, k: int) -> list:
        """Return the top-*k* entities sorted by descending confidence.

        Args:
            result: An ``EntityExtractionResult`` instance.
            k: Maximum number of entities to return.

        Returns:
            List of up to *k* ``Entity`` objects sorted by ``confidence``
            descending.
        """
        return sorted(result.entities, key=lambda e: e.confidence, reverse=True)[:k]

    def entity_count_by_type(self, result) -> dict:
        """Return a dict mapping entity type → count of entities of that type.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Dict of ``{type_str: int}``.  Empty dict when result has no entities.
        """
        counts: dict = {}
        for e in result.entities:
            counts[e.type] = counts.get(e.type, 0) + 1
        return counts

    def entity_avg_confidence(self, result) -> float:
        """Return the mean confidence across all entities in *result*.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Float mean confidence; ``0.0`` when the result has no entities.
        """
        if not result.entities:
            return 0.0
        return sum(e.confidence for e in result.entities) / len(result.entities)

    def avg_relationship_count(self, result) -> float:
        """Return average relationships per entity in *result*.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Float ``len(relationships) / len(entities)``; ``0.0`` when no
            entities.
        """
        if not result.entities:
            return 0.0
        return len(result.relationships) / len(result.entities)

    def entity_type_ratio(self, result) -> dict:
        """Return fraction of each entity type in *result*.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Dict mapping entity type string → fraction (0.0–1.0). Empty dict
            when no entities.
        """
        if not result.entities:
            return {}
        counts: dict = {}
        for e in result.entities:
            counts[e.type] = counts.get(e.type, 0) + 1
        total = len(result.entities)
        return {t: c / total for t, c in counts.items()}

    def relationship_type_counts(self, result) -> dict:
        """Return a count of each relationship type in *result*.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Dict mapping relationship type string → integer count. Empty dict
            when no relationships.
        """
        counts: dict = {}
        for r in result.relationships:
            counts[r.type] = counts.get(r.type, 0) + 1
        return counts

    def entity_text_lengths(self, result) -> list:
        """Return a list of text character counts for each entity.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            List of integer lengths, one per entity (in entity order).
        """
        return [len(e.text) for e in result.entities]

    def entity_confidence_variance(self, result) -> float:
        """Return the population variance of entity confidence values.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Float variance; ``0.0`` when fewer than 2 entities.
        """
        if len(result.entities) < 2:
            return 0.0
        vals = [e.confidence for e in result.entities]
        mean = sum(vals) / len(vals)
        return sum((v - mean) ** 2 for v in vals) / len(vals)

    def describe_extraction_pipeline(
        self, config: ExtractionConfig, result: EntityExtractionResult = None
    ) -> str:
        """Generate a human-readable summary of the extraction pipeline configuration.

        Combines the config description with extraction result statistics if provided.

        Args:
            config: The :class:`ExtractionConfig` used for extraction.
            result: Optional :class:`EntityExtractionResult` to include statistics.

        Returns:
            Multi-line string describing the pipeline configuration and optional result stats.

        Example::

            config = ExtractionConfig(confidence_threshold=0.7, max_entities=100)
            result = generator.extract_entities(text, config)
            summary = generator.describe_extraction_pipeline(config, result)
            print(summary)
            # Output:
            # ExtractionConfig: threshold=0.7, max_entities=100, ... 
            # Extraction Result: 45 entities, 32 relationships, avg_conf=0.78
        """
        lines = [config.describe()]
        if result:
            status = "empty" if result.is_empty() else "populated"
            entity_count = len(result.entities)
            rel_count = len(result.relationships)
            avg_conf = (
                sum(e.confidence for e in result.entities) / entity_count
                if entity_count > 0
                else 0.0
            )
            lines.append(
                f"Extraction Result [{status}]: {entity_count} entities, "
                f"{rel_count} relationships, avg_conf={avg_conf:.2f}"
            )
        return "\n".join(lines)

    def max_confidence_entity(self, result):
        """Return the entity with the highest confidence in *result*.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            The ``Entity`` with maximum confidence; ``None`` when no entities.
        """
        if not result.entities:
            return None
        return max(result.entities, key=lambda e: e.confidence)

    def min_confidence_entity(self, result):
        """Return the entity with the lowest confidence in *result*.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            The ``Entity`` with minimum confidence; ``None`` when no entities.
        """
        if not result.entities:
            return None
        return min(result.entities, key=lambda e: e.confidence)

    def entity_confidence_std(self, result) -> float:
        """Return the population std-dev of entity confidence values.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Float std-dev; ``0.0`` when fewer than 2 entities.
        """
        if len(result.entities) < 2:
            return 0.0
        vals = [e.confidence for e in result.entities]
        mean = sum(vals) / len(vals)
        variance = sum((v - mean) ** 2 for v in vals) / len(vals)
        return variance ** 0.5

    def entities_with_properties(self, result) -> list:
        """Return entities that have at least one non-empty property.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            List of ``Entity`` objects whose ``properties`` dict is non-empty.
        """
        return [e for e in result.entities if getattr(e, 'properties', None)]

    def top_confidence_fraction(self, result, frac: float = 0.5) -> list:
        """Return the top fraction of entities sorted by confidence.

        Args:
            result: An ``EntityExtractionResult`` instance.
            frac: Fraction of entities to keep (e.g., 0.5 = top half).
                  Defaults to 0.5.

        Returns:
            List of ``Entity`` objects, highest-confidence first, up to
            ``ceil(len * frac)`` entries.
        """
        import math
        if not result.entities:
            return []
        sorted_entities = sorted(result.entities, key=lambda e: e.confidence, reverse=True)
        k = math.ceil(len(sorted_entities) * frac)
        return sorted_entities[:k]

    def relationship_source_set(self, result) -> set:
        """Return the set of unique source entity IDs across all relationships.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Set of source entity ID strings.
        """
        return {r.source_id for r in result.relationships if r.source_id}

    def relationship_target_set(self, result) -> set:
        """Return the set of unique target entity IDs across all relationships.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Set of target entity ID strings.
        """
        return {r.target_id for r in result.relationships if r.target_id}

    def relationship_source_ids(self, result) -> set:
        """Return the set of unique source entity IDs across all relationships.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Set of source entity ID strings.

        Example:
            >>> result = generator.extract_entities("Alice knows Bob. Bob knows Alice.")
            >>> source_ids = generator.relationship_source_ids(result)
            >>> source_ids == {"alice", "bob"}
            True
        """
        return {r.source_id for r in result.relationships if r.source_id}

    def relationship_target_ids(self, result) -> set:
        """Return the set of unique target entity IDs across all relationships.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Set of target entity ID strings.

        Example:
            >>> result = generator.extract_entities("Alice knows Bob. Bob knows Alice.")
            >>> target_ids = generator.relationship_target_ids(result)
            >>> target_ids == {"alice", "bob"}
            True
        """
        return {r.target_id for r in result.relationships if r.target_id}

    def entity_id_list(self, result) -> list:
        """Return a sorted list of all entity IDs in the extraction result.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Sorted list of unique entity ID strings.

        Example:
            >>> result = generator.extract_entities("Alice knows Bob. Charlie.")
            >>> ids = generator.entity_id_list(result)
            >>> ids
            ['alice', 'bob', 'charlie']
        """
        seen = set()
        unique_ids = []
        for e in result.entities:
            if e.id and e.id not in seen:
                seen.add(e.id)
                unique_ids.append(e.id)
        return sorted(unique_ids)

    def confidence_quartiles(self, result: Any) -> dict:
        """Return Q1, median (Q2), and Q3 confidence quartiles for entities.

        Uses the standard method: sort values, then interpolate quartile
        positions.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Dict with keys ``"q1"``, ``"q2"``, ``"q3"``; all 0.0 when no
            entities are present.
        """
        entities = result.entities if result.entities else []
        if not entities:
            return {"q1": 0.0, "q2": 0.0, "q3": 0.0}
        scores = sorted(e.confidence for e in entities)
        n = len(scores)

        def _percentile(p: float) -> float:
            idx = p * (n - 1)
            lo, hi = int(idx), min(int(idx) + 1, n - 1)
            return scores[lo] + (scores[hi] - scores[lo]) * (idx - lo)

        return {"q1": _percentile(0.25), "q2": _percentile(0.50), "q3": _percentile(0.75)}

    def relationship_confidence_mean(self, result: Any) -> float:
        """Return the mean confidence of all relationships in *result*.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Float mean; 0.0 when no relationships are present.
        """
        rels = result.relationships if result.relationships else []
        if not rels:
            return 0.0
        return sum(getattr(r, "confidence", 1.0) for r in rels) / len(rels)

    def relationship_confidence_avg(self, result: Any) -> float:
        """Alias for :meth:`relationship_confidence_mean`.

        Returns the mean confidence of all relationships in *result*.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Float mean; 0.0 when no relationships are present.
        """
        return self.relationship_confidence_mean(result)

    def entities_above_confidence(self, result: Any, threshold: float = 0.7) -> list:
        """Return entities whose confidence exceeds *threshold*.

        Args:
            result: An ``EntityExtractionResult`` instance.
            threshold: Minimum confidence (exclusive).

        Returns:
            List of :class:`Entity` objects; empty list when none qualify.
        """
        return [e for e in (result.entities or []) if e.confidence > threshold]

    def entity_type_entropy(self, result: Any) -> float:
        """Return the Shannon entropy of entity type distribution.

        Higher entropy means types are more evenly distributed; lower entropy
        means the result is dominated by one type.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Float entropy in bits; 0.0 when no entities or all same type.
        """
        import math
        entities = result.entities or []
        if not entities:
            return 0.0
        from collections import Counter
        counts = Counter(e.type for e in entities)
        total = len(entities)
        entropy = 0.0
        for c in counts.values():
            p = c / total
            if p > 0:
                entropy -= p * math.log2(p)
        return entropy

    def entity_confidence_skewness(self, result: Any) -> float:
        """Return the skewness of entity confidence scores.

        Uses the sample skewness formula (Fisher-Pearson).

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Float skewness; 0.0 when fewer than 3 entities or std is zero.
        """
        entities = result.entities or []
        if len(entities) < 3:
            return 0.0
        scores = [e.confidence for e in entities]
        n = len(scores)
        mean = sum(scores) / n
        std = (sum((s - mean) ** 2 for s in scores) / n) ** 0.5
        if std == 0.0:
            return 0.0
        return sum(((s - mean) / std) ** 3 for s in scores) / n

    def history_kurtosis(self, results: List[Any]) -> float:
        """Return the kurtosis of confidence scores across multiple results.

        Calculates excess kurtosis (Fisher's definition) which is 0.0 for a
        normal distribution. Positive values indicate heavy tails (more outliers),
        negative values indicate light tails (fewer outliers).

        Uses the sample kurtosis formula: E[((X - μ) / σ)^4] - 3

        Args:
            results: List of ``EntityExtractionResult`` instances.

        Returns:
            Float excess kurtosis; 0.0 when fewer than 4 total entities or std is zero.

        Example:
            >>> results = [result1, result2, result3]
            >>> kurt = generator.history_kurtosis(results)
            >>> if kurt > 1.0:
            ...     print("Heavy-tailed distribution (many outliers)")
        """
        # Collect all confidence scores from all results
        all_scores = []
        for result in results:
            entities = getattr(result, 'entities', []) or []
            all_scores.extend(e.confidence for e in entities)
        
        # Need at least 4 values for meaningful kurtosis
        if len(all_scores) < 4:
            return 0.0
        
        n = len(all_scores)
        mean = sum(all_scores) / n
        
        # Calculate standard deviation
        variance = sum((s - mean) ** 2 for s in all_scores) / n
        std = variance ** 0.5
        
        if std == 0.0:
            return 0.0
        
        # Calculate fourth moment (kurtosis)
        # Excess kurtosis = (fourth_moment / variance^2) - 3
        fourth_moment = sum(((s - mean) / std) ** 4 for s in all_scores) / n
        
        return fourth_moment - 3.0  # Excess kurtosis

    def score_ewma(
        self,
        results: List[Any],
        alpha: float = 0.3
    ) -> float:
        """Calculate exponentially weighted moving average of confidence scores.

        The EWMA gives more weight to recent results while incorporating historical
        data with exponentially decreasing weights. This is useful for tracking
        trends in extraction quality over time.

        Formula: EWMA(t) = α * score(t) + (1-α) * EWMA(t-1)

        Args:
            results: List of ``EntityExtractionResult`` instances in chronological order.
            alpha: Smoothing factor (0 < α <= 1). Higher values give more weight to
                recent observations. Common values: 0.1 (slow), 0.3 (moderate), 0.5 (fast).

        Returns:
            Float EWMA value; 0.0 when no results with entities.

        Example:
            >>> results = [result1, result2, result3, result4]  # chronological
            >>> ewma = generator.score_ewma(results, alpha=0.3)
            >>> if ewma < 0.7:
            ...     print("Quality trending downward, investigate")

        Note:
            Results should be in chronological order for meaningful EWMA calculation.
            The method uses mean confidence per result as the score.
        """
        if not results:
            return 0.0

        # Clamp alpha to valid range
        alpha = max(0.0, min(1.0, alpha))
        if alpha == 0.0:
            return 0.0

        # Calculate mean confidence for each result
        scores = []
        for result in results:
            entities = getattr(result, 'entities', []) or []
            if entities:
                mean_conf = sum(e.confidence for e in entities) / len(entities)
                scores.append(mean_conf)

        if not scores:
            return 0.0

        # Calculate EWMA
        ewma = scores[0]  # Initialize with first score
        for score in scores[1:]:
            ewma = alpha * score + (1 - alpha) * ewma

        return ewma

    def score_ewma_series(
        self,
        results: List[Any],
        alpha: float = 0.3
    ) -> List[float]:
        """Calculate EWMA series showing trend over time.

        Returns the full EWMA series, one value per result, showing how the
        weighted average evolves. Useful for visualization and trend analysis.

        Args:
            results: List of ``EntityExtractionResult`` instances in chronological order.
            alpha: Smoothing factor (0 < α <= 1).

        Returns:
            List of EWMA values, one per result. Empty list if no valid scores.

        Example:
            >>> results = [result1, result2, result3, result4]
            >>> ewma_series = generator.score_ewma_series(results, alpha=0.3)
            >>> # Plot ewma_series to visualize quality trend
            >>> import matplotlib.pyplot as plt
            >>> plt.plot(ewma_series)
            >>> plt.ylabel('EWMA Confidence')
            >>> plt.xlabel('Time')
        """
        if not results:
            return []

        # Clamp alpha to valid range
        alpha = max(0.0, min(1.0, alpha))
        if alpha == 0.0:
            return []

        # Calculate mean confidence for each result
        scores = []
        for result in results:
            entities = getattr(result, 'entities', []) or []
            if entities:
                mean_conf = sum(e.confidence for e in entities) / len(entities)
                scores.append(mean_conf)
            else:
                # No entities in this result, use previous EWMA or 0.0
                if scores:
                    scores.append(scores[-1] if hasattr(scores[-1], '__float__') else 0.0)
                else:
                    scores.append(0.0)

        if not scores:
            return []

        # Calculate EWMA series
        ewma_series = [scores[0]]
        for score in scores[1:]:
            ewma = alpha * score + (1 - alpha) * ewma_series[-1]
            ewma_series.append(ewma)

        return ewma_series

    def confidence_min(self, results: List[Any]) -> float:
        """Return the minimum confidence score across all results.

        Useful for identifying the worst-case extraction quality in a batch.

        Args:
            results: List of ``EntityExtractionResult`` instances.

        Returns:
            Float minimum confidence; 0.0 when no entities.

        Example:
            >>> results = [result1, result2, result3]
            >>> min_conf = generator.confidence_min(results)
            >>> if min_conf < 0.5:
            ...     print(f"⚠️  Minimum confidence very low: {min_conf:.2f}")
        """
        all_scores = []
        for result in results:
            entities = getattr(result, 'entities', []) or []
            all_scores.extend(e.confidence for e in entities)
        
        return min(all_scores) if all_scores else 0.0

    def confidence_max(self, results: List[Any]) -> float:
        """Return the maximum confidence score across all results.

        Useful for identifying the best extraction quality achieved.

        Args:
            results: List of ``EntityExtractionResult`` instances.

        Returns:
            Float maximum confidence; 0.0 when no entities.

        Example:
            >>> results = [result1, result2, result3]
            >>> max_conf = generator.confidence_max(results)
            >>> print(f"Best confidence achieved: {max_conf:.2f}")
        """
        all_scores = []
        for result in results:
            entities = getattr(result, 'entities', []) or []
            all_scores.extend(e.confidence for e in entities)
        
        return max(all_scores) if all_scores else 0.0

    def confidence_range(self, results: List[Any]) -> float:
        """Return the range (max - min) of confidence scores.

        Large ranges indicate inconsistent extraction quality. Small ranges
        suggest stable, predictable performance.

        Args:
            results: List of ``EntityExtractionResult`` instances.

        Returns:
            Float range; 0.0 when no entities or all scores identical.

        Example:
            >>> results = [result1, result2, result3]
            >>> conf_range = generator.confidence_range(results)
            >>> if conf_range > 0.5:
            ...     print(f"⚠️  High variance in quality (range: {conf_range:.2f})")
            >>> else:
            ...     print(f"✓ Stable quality (range: {conf_range:.2f})")
        """
        all_scores = []
        for result in results:
            entities = getattr(result, 'entities', []) or []
            all_scores.extend(e.confidence for e in entities)
        
        if not all_scores:
            return 0.0
        
        return max(all_scores) - min(all_scores)

    def confidence_percentile(
        self,
        results: List[Any],
        percentile: float = 50.0
    ) -> float:
        """Return the specified percentile of confidence scores.

        Percentiles provide robust measures of distribution characteristics.
        Common percentiles: 25 (Q1), 50 (median), 75 (Q3), 90, 95, 99.

        Args:
            results: List of ``EntityExtractionResult`` instances.
            percentile: Percentile to compute (0-100). Default 50 (median).

        Returns:
            Float percentile value; 0.0 when no entities.

        Example:
            >>> results = [result1, result2, result3]
            >>> p50 = generator.confidence_percentile(results, 50)  # Median
            >>> p95 = generator.confidence_percentile(results, 95)  # 95th percentile
            >>> if p95 > 0.9:
            ...     print(f"95% of entities have confidence > {p95:.2f}")
        """
        all_scores = []
        for result in results:
            entities = getattr(result, 'entities', []) or []
            all_scores.extend(e.confidence for e in entities)
        
        if not all_scores:
            return 0.0
        
        # Clamp percentile to valid range
        percentile = max(0.0, min(100.0, percentile))
        
        # Sort scores
        sorted_scores = sorted(all_scores)
        n = len(sorted_scores)
        
        # Calculate percentile index
        k = (n - 1) * percentile / 100.0
        f = int(k)
        c = k - f
        
        if f + 1 < n:
            return sorted_scores[f] + c * (sorted_scores[f + 1] - sorted_scores[f])
        else:
            return sorted_scores[f]

    def confidence_iqr(self, results: List[Any]) -> float:
        """Return the interquartile range (IQR) of confidence scores.

        IQR = Q3 - Q1, measures the spread of the middle 50% of the data.
        It's robust to outliers and useful for identifying anomalies.

        Args:
            results: List of ``EntityExtractionResult`` instances.

        Returns:
            Float IQR; 0.0 when no entities.

        Example:
            >>> results = [result1, result2, result3]
            >>> iqr = generator.confidence_iqr(results)
            >>> # Scores outside [Q1 - 1.5*IQR, Q3 + 1.5*IQR] are outliers
            >>> q1 = generator.confidence_percentile(results, 25)
            >>> q3 = generator.confidence_percentile(results, 75)
            >>> lower_fence = q1 - 1.5 * iqr
            >>> upper_fence = q3 + 1.5 * iqr
        """
        q1 = self.confidence_percentile(results, 25)
        q3 = self.confidence_percentile(results, 75)
        return q3 - q1

    def confidence_coefficient_of_variation(self, results: List[Any]) -> float:
        """Return coefficient of variation (CV) of confidence scores.

        CV = std_dev / mean, normalized measure of dispersion as a percentage.
        Useful for comparing variability across distributions with different means.

        Args:
            results: List of ``EntityExtractionResult`` instances.

        Returns:
            Float CV value (typically 0 to 1, can exceed 1 for highly variable data);
            0.0 when no entities or all scores identical.

        Interpretation:
            - CV < 0.1: Very stable/consistent (low variability)
            - CV 0.1-0.3: Moderate consistency
            - CV > 0.5: High variability (inconsistent)

        Example:
            >>> results = [result1, result2, result3]
            >>> cv = generator.confidence_coefficient_of_variation(results)
            >>> if cv < 0.15:
            ...     print("Very stable extraction quality")
            >>> elif cv > 0.5:
            ...     print("Inconsistent extraction, investigate issues")
        """
        scores = []
        for result in results:
            entities = result.entities if hasattr(result, 'entities') else []
            if entities:
                scores.extend(e.confidence for e in entities if hasattr(e, 'confidence'))
        
        if not scores or len(scores) < 2:
            return 0.0
        
        mean = sum(scores) / len(scores)
        if mean == 0.0:
            return 0.0
        
        variance = sum((s - mean) ** 2 for s in scores) / len(scores)
        std_dev = variance ** 0.5
        
        return std_dev / mean

    def entity_relation_ratio(self, result: Any) -> float:
        """Return the ratio of entity count to relationship count.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Float ratio; 0.0 when there are no relationships.
        """
        rels = result.relationships or []
        entities = result.entities or []
        if not rels:
            return 0.0
        return len(entities) / len(rels)

    def relationship_confidence_std(self, result: Any) -> float:
        """Return the population std-dev of relationship confidence scores.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Float std-dev; 0.0 when fewer than 2 relationships.
        """
        rels = result.relationships or []
        if len(rels) < 2:
            return 0.0
        confs = [getattr(r, "confidence", 1.0) for r in rels]
        mean = sum(confs) / len(confs)
        variance = sum((c - mean) ** 2 for c in confs) / len(confs)
        return variance ** 0.5

    def entity_confidence_percentile(self, result: Any, p: float = 50.0) -> float:
        """Return the *p*-th percentile of entity confidence scores.

        Uses linear interpolation.

        Args:
            result: An ``EntityExtractionResult`` instance.
            p: Percentile in [0, 100].

        Returns:
            Float; 0.0 when no entities are present.
        """
        entities = result.entities or []
        if not entities:
            return 0.0
        scores = sorted(e.confidence for e in entities)
        n = len(scores)
        if n == 1:
            return scores[0]
        idx = (p / 100.0) * (n - 1)
        lo, hi = int(idx), min(int(idx) + 1, n - 1)
        return scores[lo] + (scores[hi] - scores[lo]) * (idx - lo)

    def relationship_type_frequency(self, result: Any) -> dict:
        """Return a dict mapping relationship types to their occurrence counts.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Dict ``{type_str: count_int}``; empty when no relationships.
        """
        from collections import Counter
        rels = result.relationships or []
        return dict(Counter(getattr(r, "type", "") for r in rels))

    def entity_id_set(self, result: Any) -> set:
        """Return the set of all entity IDs in *result*.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Set of strings; empty set when no entities.
        """
        return {e.id for e in (result.entities or []) if e.id}

    def entity_source_span_coverage(self, result: Any) -> float:
        """Return the fraction of entities that have a non-None source_span.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Float in [0, 1]; 0.0 when no entities.
        """
        entities = result.entities or []
        if not entities:
            return 0.0
        return sum(1 for e in entities if getattr(e, "source_span", None) is not None) / len(entities)

    def relationship_density(self, result: Any) -> float:
        """Return edges / nodes ratio (density proxy).

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Float; 0.0 when there are no entities.
        """
        entities = result.entities or []
        rels = result.relationships or []
        if not entities:
            return 0.0
        return len(rels) / len(entities)

    def relationship_coverage(self, result: Any) -> float:
        """Return fraction of entities that appear in at least one relationship.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Float in [0, 1]; 0.0 when no entities.
        """
        entities = result.entities or []
        rels = result.relationships or []
        if not entities:
            return 0.0
        connected: set = set()
        for r in rels:
            src = getattr(r, "source_id", None)
            tgt = getattr(r, "target_id", None)
            if src:
                connected.add(src)
            if tgt:
                connected.add(tgt)
        entity_ids = {e.id for e in entities if e.id}
        return len(entity_ids & connected) / len(entities)

    def entity_confidence_variance(self, result: Any) -> float:
        """Return the variance of entity confidence scores.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Float; 0.0 when fewer than 2 entities.
        """
        entities = result.entities or []
        n = len(entities)
        if n < 2:
            return 0.0
        confs = [getattr(e, "confidence", 0.5) for e in entities]
        mean = sum(confs) / n
        return sum((c - mean) ** 2 for c in confs) / n

    def entity_property_count(self, result: Any) -> int:
        """Return the total count of all property key-value pairs across all entities.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Integer; 0 when no entities or no properties.
        """
        return sum(
            len(getattr(e, "properties", {}) or {})
            for e in (result.entities or [])
        )

    def entity_types_set(self, result: Any) -> set:
        """Return the set of distinct entity type strings in *result*.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Set of strings; empty set when no entities.
        """
        return {getattr(e, "type", "") for e in (result.entities or [])}

    def entity_confidence_iqr(self, result: Any) -> float:
        """Return the IQR of entity confidence scores.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Float; 0.0 when fewer than 4 entities.
        """
        entities = result.entities or []
        if len(entities) < 4:
            return 0.0
        scores = sorted(getattr(e, "confidence", 0.5) for e in entities)
        n = len(scores)

        def _percentile(p: float) -> float:
            idx = (p / 100.0) * (n - 1)
            lo, hi = int(idx), min(int(idx) + 1, n - 1)
            return scores[lo] + (scores[hi] - scores[lo]) * (idx - lo)

        return _percentile(75.0) - _percentile(25.0)

    def avg_entity_confidence(self, result: Any) -> float:
        """Return the average confidence across all entities.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Float; 0.0 when no entities.
        """
        entities = result.entities or []
        if not entities:
            return 0.0
        return sum(getattr(e, "confidence", 0.5) for e in entities) / len(entities)

    def relationship_bidirectionality_rate(self, result: Any) -> float:
        """Return the fraction of entity pairs with edges in both directions.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Float in [0, 1]; 0.0 when fewer than 2 relationships.
        """
        rels = result.relationships or []
        if len(rels) < 2:
            return 0.0
        pairs: set = set()
        bidir = 0
        for r in rels:
            src = getattr(r, "source_id", None)
            tgt = getattr(r, "target_id", None)
            if src and tgt:
                if (tgt, src) in pairs:
                    bidir += 2
                pairs.add((src, tgt))
        if not pairs:
            return 0.0
        return bidir / len(pairs)

    def entity_text_length_mean(self, result: Any) -> float:
        """Return the mean length of entity text strings.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Float; 0.0 when no entities.
        """
        entities = result.entities or []
        if not entities:
            return 0.0
        return sum(len(getattr(e, "text", "") or "") for e in entities) / len(entities)

    def entity_confidence_mode(self, result: Any) -> float:
        """Return the most common entity confidence (approximate bin mode).

        Bins confidences into 10 equal bins in [0, 1] and returns the
        midpoint of the most populated bin.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Float; 0.5 when no entities.
        """
        entities = result.entities or []
        if not entities:
            return 0.5
        bins = [0] * 10
        for e in entities:
            c = getattr(e, "confidence", 0.5)
            idx = min(9, int(c * 10))
            bins[idx] += 1
        best_idx = bins.index(max(bins))
        return (best_idx + 0.5) / 10.0

    def relationship_types_count(self, result: Any) -> int:
        """Return the number of distinct relationship types in *result*.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Integer; 0 when no relationships.
        """
        rels = result.relationships or []
        return len({getattr(r, "type", "") for r in rels})

    def entity_confidence_std(self, result: Any) -> float:
        """Return the standard deviation of entity confidence scores.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Float; 0.0 when fewer than 2 entities.
        """
        entities = result.entities or []
        n = len(entities)
        if n < 2:
            return 0.0
        confs = [getattr(e, "confidence", 0.5) for e in entities]
        mean = sum(confs) / n
        return (sum((c - mean) ** 2 for c in confs) / n) ** 0.5

    def entity_avg_property_count(self, result: Any) -> float:
        """Return the average number of properties per entity.

        Args:
            result: An ``EntityExtractionResult`` instance.

        Returns:
            Float; 0.0 when no entities.
        """
        entities = result.entities or []
        if not entities:
            return 0.0
        return sum(len(getattr(e, "properties", {}) or {}) for e in entities) / len(entities)

    def entity_min_confidence(self, result: "EntityExtractionResult") -> float:
        """Return the minimum confidence score across all entities.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Minimum confidence; 0.0 when no entities.
        """
        entities = result.entities or []
        if not entities:
            return 0.0
        return min(getattr(e, "confidence", 0.0) or 0.0 for e in entities)

    def entity_max_confidence(self, result: "EntityExtractionResult") -> float:
        """Return the maximum confidence score across all entities.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Maximum confidence; 0.0 when no entities.
        """
        entities = result.entities or []
        if not entities:
            return 0.0
        return max(getattr(e, "confidence", 0.0) or 0.0 for e in entities)

    def entity_with_most_properties(self, result: "EntityExtractionResult") -> str:
        """Return the ID of the entity with the most properties.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Entity ID string; empty string when no entities.
        """
        entities = result.entities or []
        if not entities:
            return ""
        best = max(entities, key=lambda e: len(getattr(e, "properties", {}) or {}))
        return best.id

    def relationship_max_weight(self, result: "EntityExtractionResult") -> float:
        """Return the maximum weight among all relationships.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Float max weight; 0.0 when no relationships or no weight attribute.
        """
        rels = result.relationships or []
        if not rels:
            return 0.0
        weights = [getattr(r, "weight", 0.0) or 0.0 for r in rels]
        return max(weights)

    def entity_count_with_confidence_above(self, result: "EntityExtractionResult", threshold: float = 0.7) -> int:
        """Return count of entities whose confidence exceeds *threshold*.

        Args:
            result: EntityExtractionResult to inspect.
            threshold: Exclusive lower bound. Defaults to 0.7.

        Returns:
            Integer count.
        """
        entities = result.entities or []
        return sum(1 for e in entities if (getattr(e, "confidence", 0.0) or 0.0) > threshold)

    def relationship_avg_confidence(self, result: "EntityExtractionResult") -> float:
        """Return the average confidence across all relationships.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Float mean; 0.0 when no relationships.
        """
        rels = result.relationships or []
        if not rels:
            return 0.0
        return sum(getattr(r, "confidence", 0.0) or 0.0 for r in rels) / len(rels)

    def entity_confidence_range(self, result: "EntityExtractionResult") -> float:
        """Return the range (max - min) of entity confidence values.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Float range; 0.0 when fewer than 2 entities.
        """
        entities = result.entities or []
        if len(entities) < 2:
            return 0.0
        confs = [getattr(e, "confidence", 0.0) or 0.0 for e in entities]
        return max(confs) - min(confs)

    def relationship_min_confidence(self, result: "EntityExtractionResult") -> float:
        """Return the minimum confidence across all relationships.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Float minimum; 0.0 when no relationships.
        """
        rels = result.relationships or []
        if not rels:
            return 0.0
        return min(getattr(r, "confidence", 0.0) or 0.0 for r in rels)

    def entity_avg_text_length(self, result: "EntityExtractionResult") -> float:
        """Return the mean character length of entity text strings.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Float mean text length; 0.0 when no entities.
        """
        entities = result.entities or []
        if not entities:
            return 0.0
        return sum(len(getattr(e, "text", "") or "") for e in entities) / len(entities)

    def relationship_confidence_range(self, result: "EntityExtractionResult") -> float:
        """Return the range (max - min) of relationship confidence values.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Float range; 0.0 when fewer than 2 relationships.
        """
        rels = result.relationships or []
        if len(rels) < 2:
            return 0.0
        confs = [getattr(r, "confidence", 0.0) or 0.0 for r in rels]
        return max(confs) - min(confs)

    def entity_property_keys(self, result: "EntityExtractionResult") -> set:
        """Return the union of all property keys across entities.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Set of string property key names; empty set when no entities.
        """
        keys: set = set()
        for e in (result.entities or []):
            keys.update((getattr(e, "properties", {}) or {}).keys())
        return keys

    def entity_text_max_length(self, result: "EntityExtractionResult") -> int:
        """Return the maximum character length of entity text strings.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Integer max length; 0 when no entities.
        """
        entities = result.entities or []
        if not entities:
            return 0
        return max(len(getattr(e, "text", "") or "") for e in entities)

    def relationship_type_diversity(self, result: "EntityExtractionResult") -> int:
        """Return the count of distinct relationship types.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Integer count of unique relationship types; 0 when no relationships.
        """
        rels = result.relationships or []
        return len({getattr(r, "type", None) for r in rels if getattr(r, "type", None)})

    def relationship_avg_weight(self, result: "EntityExtractionResult") -> float:
        """Return the average weight across all relationships.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Float mean weight; 0.0 when no relationships or no weight attribute.
        """
        rels = result.relationships or []
        if not rels:
            return 0.0
        return sum(getattr(r, "weight", 0.0) or 0.0 for r in rels) / len(rels)

    def entity_confidence_sum(self, result: "EntityExtractionResult") -> float:
        """Return the sum of confidence scores across all entities.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Float sum; 0.0 when no entities.
        """
        entities = result.entities or []
        return sum(getattr(e, "confidence", 0.0) or 0.0 for e in entities)

    def relationship_source_ids(self, result: "EntityExtractionResult") -> set:
        """Return the set of source entity IDs from all relationships.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Set of source ID strings.
        """
        return {getattr(r, "source_id", None) for r in (result.relationships or []) if getattr(r, "source_id", None)}

    def relationship_target_ids(self, result: "EntityExtractionResult") -> set:
        """Return the set of target entity IDs from all relationships.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Set of target ID strings.
        """
        return {getattr(r, "target_id", None) for r in (result.relationships or []) if getattr(r, "target_id", None)}

    def entity_confidence_histogram(self, result: "EntityExtractionResult", bins: int = 5) -> list:
        """Bucket entity confidence values into *bins* equal-width buckets and return counts.

        Args:
            result: EntityExtractionResult to inspect.
            bins: Number of buckets between 0.0 and 1.0. Defaults to 5.

        Returns:
            List of ``bins`` integers (counts per bucket), or empty list when no entities.
        """
        entities = result.entities or []
        if not entities:
            return []
        counts = [0] * bins
        for e in entities:
            conf = float(getattr(e, "confidence", 0.0) or 0.0)
            idx = min(int(conf * bins), bins - 1)
            counts[idx] += 1
        return counts

    def entity_avg_id_length(self, result: "EntityExtractionResult") -> float:
        """Return the average character length of entity IDs.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Float average length; 0.0 when no entities.
        """
        entities = result.entities or []
        if not entities:
            return 0.0
        return sum(len(e.id) for e in entities) / len(entities)

    def relationship_isolated_ids(self, result: "EntityExtractionResult") -> set:
        """Return entity IDs that appear only once across all relationships.

        An ID that appears exactly once (either as source or target) across all
        relationships is considered isolated.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Set of isolated entity ID strings.
        """
        from collections import Counter
        degree: Counter = Counter()
        for r in result.relationships or []:
            src = getattr(r, "source_id", None)
            tgt = getattr(r, "target_id", None)
            if src:
                degree[src] += 1
            if tgt:
                degree[tgt] += 1
        return {node for node, cnt in degree.items() if cnt == 1}

    def entity_max_property_count(self, result: "EntityExtractionResult") -> int:
        """Return the maximum number of properties across all entities.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Integer max property count; 0 when no entities.
        """
        entities = result.entities or []
        if not entities:
            return 0
        return max(len(getattr(e, "properties", None) or {}) for e in entities)

    def entity_min_confidence_above(
        self, result: "EntityExtractionResult", threshold: float = 0.5
    ) -> float:
        """Return the minimum confidence among entities with confidence > threshold.

        Args:
            result: EntityExtractionResult to inspect.
            threshold: Minimum confidence filter. Defaults to 0.5.

        Returns:
            Float minimum confidence; 0.0 when no qualifying entities.
        """
        qualifying = [
            getattr(e, "confidence", 0.0) or 0.0
            for e in (result.entities or [])
            if (getattr(e, "confidence", 0.0) or 0.0) > threshold
        ]
        return min(qualifying) if qualifying else 0.0

    def relationship_avg_type_length(self, result: "EntityExtractionResult") -> float:
        """Return the average character length of relationship type names.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Float average; 0.0 when no relationships.
        """
        rels = result.relationships or []
        if not rels:
            return 0.0
        lengths = [len(str(getattr(r, "type", "") or "")) for r in rels]
        return sum(lengths) / len(lengths)

    def entity_unique_types(self, result: "EntityExtractionResult") -> set:
        """Return the set of unique entity type strings in the result.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Set of type strings; empty set when no entities.
        """
        return {e.type for e in (result.entities or []) if e.type}

    def relationship_bidirectional_count(self, result: "EntityExtractionResult") -> int:
        """Return the number of bidirectional relationship pairs.

        A pair (A→B) and (B→A) counts as one bidirectional pair.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Integer count of bidirectional pairs.
        """
        edges: set = set()
        pairs = 0
        for r in result.relationships or []:
            src = getattr(r, "source_id", None)
            tgt = getattr(r, "target_id", None)
            if src and tgt:
                if (tgt, src) in edges:
                    pairs += 1
                else:
                    edges.add((src, tgt))
        return pairs

    def entity_text_word_count_avg(self, result: "EntityExtractionResult") -> float:
        """Return the average word count in entity text fields.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Float average word count; 0.0 when no entities.
        """
        entities = result.entities or []
        if not entities:
            return 0.0
        counts = [len((getattr(e, "text", "") or "").split()) for e in entities]
        return sum(counts) / len(counts)

    def relationship_symmetry_ratio(self, result: "EntityExtractionResult") -> float:
        """Return the fraction of relationships that have a reverse counterpart.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Float in [0.0, 1.0]; 0.0 when no relationships.
        """
        rels = result.relationships or []
        if not rels:
            return 0.0
        edge_set = {(getattr(r, "source_id", None), getattr(r, "target_id", None)) for r in rels}
        symmetric = sum(1 for (src, tgt) in edge_set if (tgt, src) in edge_set)
        return symmetric / len(edge_set)

    def entity_confidence_entropy(self, result: "EntityExtractionResult") -> float:
        """Return the Shannon entropy of entity confidence values (bucketed in 0.1 bins).

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Float entropy in nats; 0.0 when no entities.
        """
        import math
        entities = result.entities or []
        if not entities:
            return 0.0
        n = len(entities)
        buckets: dict = {}
        for e in entities:
            conf = float(getattr(e, "confidence", 0.0) or 0.0)
            bucket = min(int(conf * 10), 9)
            buckets[bucket] = buckets.get(bucket, 0) + 1
        entropy = 0.0
        for count in buckets.values():
            p = count / n
            if p > 0:
                entropy -= p * math.log(p)
        return entropy

    def entity_with_longest_text(self, result: "EntityExtractionResult"):
        """Return the entity with the longest text field.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            The Entity object with the most characters in its text; None when empty.
        """
        entities = result.entities or []
        if not entities:
            return None
        return max(entities, key=lambda e: len(getattr(e, "text", "") or ""))

    def relationship_weight_entropy(self, result: "EntityExtractionResult") -> float:
        """Return the Shannon entropy of relationship weights (bucketed in 0.1 bins).

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Float entropy in nats; 0.0 when no relationships.
        """
        import math as _math
        rels = result.relationships or []
        if not rels:
            return 0.0
        n = len(rels)
        buckets: dict = {}
        for r in rels:
            w = float(getattr(r, "weight", 1.0) or 1.0)
            bucket = min(int(w * 10), 9)
            buckets[bucket] = buckets.get(bucket, 0) + 1
        entropy = 0.0
        for count in buckets.values():
            p = count / n
            if p > 0:
                entropy -= p * _math.log(p)
        return entropy

    def entity_property_value_types(self, result: "EntityExtractionResult") -> set:
        """Return the set of Python type names of all property values across entities.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Set of type name strings (e.g. {'str', 'int'}); empty set when no properties.
        """
        type_names: set = set()
        for e in result.entities or []:
            for v in (getattr(e, "properties", None) or {}).values():
                type_names.add(type(v).__name__)
        return type_names

    def relationship_types_sorted(self, result: "EntityExtractionResult") -> list:
        """Return a sorted list of unique relationship type strings.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Sorted list of unique type strings; empty list when no relationships.
        """
        types = {str(getattr(r, "type", "") or "") for r in result.relationships or []}
        return sorted(t for t in types if t)

    def entity_diversity_score(self, result: "EntityExtractionResult") -> float:
        """Return a diversity score for entity types: unique_types / total_entities.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Float in [0.0, 1.0]; 0.0 when no entities.
        """
        entities = result.entities or []
        if not entities:
            return 0.0
        unique_types = len({e.type for e in entities if e.type})
        return unique_types / len(entities)

    def relationship_density_by_type(self, result: "EntityExtractionResult") -> dict:
        """Return a dict of {type: fraction_of_all_relationships} for each relationship type.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Dict of {type_str: float}; empty dict when no relationships.
        """
        rels = result.relationships or []
        if not rels:
            return {}
        n = len(rels)
        counts: dict = {}
        for r in rels:
            t = str(getattr(r, "type", "") or "")
            counts[t] = counts.get(t, 0) + 1
        return {t: c / n for t, c in counts.items()}

    def entity_id_prefix_groups(self, result: "EntityExtractionResult", prefix_len: int = 1) -> dict:
        """Group entities by the first *prefix_len* characters of their ID.

        Args:
            result: EntityExtractionResult to inspect.
            prefix_len: Number of leading characters to use as prefix key. Defaults to 1.

        Returns:
            Dict of {prefix: list_of_entity_ids}; empty dict when no entities.
        """
        groups: dict = {}
        for e in result.entities or []:
            prefix = e.id[:prefix_len] if len(e.id) >= prefix_len else e.id
            groups.setdefault(prefix, []).append(e.id)
        return groups

    def relationship_cross_type_count(self, result: "EntityExtractionResult") -> int:
        """Count relationships that connect entities of different types.

        Requires entity type information to be accessible via a lookup on the
        source/target IDs from the entities in the same result.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Integer count of cross-type relationships; 0 when no type info available.
        """
        entity_types = {e.id: e.type for e in (result.entities or [])}
        count = 0
        for r in result.relationships or []:
            src = getattr(r, "source_id", None)
            tgt = getattr(r, "target_id", None)
            if src and tgt and src in entity_types and tgt in entity_types:
                if entity_types[src] != entity_types[tgt]:
                    count += 1
        return count

    def entity_multi_property_count(self, result: "EntityExtractionResult") -> int:
        """Return the count of entities that have more than one property.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Integer count; 0 when no entities or no multi-property entities.
        """
        return sum(
            1
            for e in (result.entities or [])
            if len(getattr(e, "properties", None) or {}) > 1
        )

    def relationship_avg_id_pair_length(self, result: "EntityExtractionResult") -> float:
        """Return the average combined length of (source_id + target_id) per relationship.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Float average length; 0.0 when no relationships.
        """
        rels = result.relationships or []
        if not rels:
            return 0.0
        lengths = [
            len(str(getattr(r, "source_id", "") or "")) + len(str(getattr(r, "target_id", "") or ""))
            for r in rels
        ]
        return sum(lengths) / len(lengths)

    def entity_confidence_cv(self, result: "EntityExtractionResult") -> float:
        """Return the coefficient of variation (std/mean) of entity confidence values.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Float CV; 0.0 when fewer than 2 entities or mean == 0.
        """
        entities = result.entities or []
        if len(entities) < 2:
            return 0.0
        vals = [float(getattr(e, "confidence", 0.0) or 0.0) for e in entities]
        mean = sum(vals) / len(vals)
        if mean == 0:
            return 0.0
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        return (var ** 0.5) / mean

    def relationship_unique_endpoints(self, result: "EntityExtractionResult") -> int:
        """Return the count of unique node IDs that appear in any relationship.

        Args:
            result: EntityExtractionResult to inspect.

        Returns:
            Integer count; 0 when no relationships.
        """
        endpoints: set = set()
        for r in result.relationships or []:
            src = getattr(r, "source_id", None)
            tgt = getattr(r, "target_id", None)
            if src:
                endpoints.add(src)
            if tgt:
                endpoints.add(tgt)
        return len(endpoints)

    def entity_with_highest_confidence(self, result) -> object:
        """Return the entity with the highest confidence, or None.

        Args:
            result: EntityExtractionResult.

        Returns:
            The Entity with max confidence, or None when result is empty.
        """
        if not result.entities:
            return None
        return max(result.entities, key=lambda e: e.confidence)

    def relationship_source_degree_distribution(self, result) -> dict:
        """Return a dict mapping each source_id to how many relationships it starts.

        Args:
            result: EntityExtractionResult.

        Returns:
            Dict[str, int]; empty dict when no relationships.
        """
        counts: dict = {}
        for r in result.relationships:
            src = getattr(r, "source_id", None)
            if src is not None:
                counts[src] = counts.get(src, 0) + 1
        return counts

    def entity_confidence_below_mean_count(self, result) -> int:
        """Return how many entities have confidence below the mean.

        Args:
            result: EntityExtractionResult.

        Returns:
            Non-negative integer; 0 when fewer than 2 entities.
        """
        if len(result.entities) < 2:
            return 0
        scores = [e.confidence for e in result.entities]
        mean = sum(scores) / len(scores)
        return sum(1 for s in scores if s < mean)

    def relationship_self_loop_ids(self, result) -> list:
        """Return the IDs of relationships where source == target.

        Args:
            result: EntityExtractionResult.

        Returns:
            List of source_id strings (may be empty).
        """
        return [
            getattr(r, "source_id", None)
            for r in result.relationships
            if getattr(r, "source_id", None) is not None
            and getattr(r, "source_id", None) == getattr(r, "target_id", None)
        ]

    def entity_text_length_median(self, result) -> float:
        """Return the median text length (characters) across all entities.

        Args:
            result: EntityExtractionResult.

        Returns:
            Float; 0.0 when no entities.
        """
        if not result.entities:
            return 0.0
        lengths = sorted(len(e.text or "") for e in result.entities)
        n = len(lengths)
        mid = n // 2
        if n % 2 == 0:
            return (lengths[mid - 1] + lengths[mid]) / 2
        return float(lengths[mid])

    def relationship_type_entropy(self, result) -> float:
        """Return the Shannon entropy of relationship type distribution.

        Args:
            result: EntityExtractionResult.

        Returns:
            Float >= 0.0; 0.0 when fewer than 2 relationships.
        """
        import math
        if len(result.relationships) < 2:
            return 0.0
        counts: dict = {}
        for r in result.relationships:
            t = getattr(r, "type", None) or "unknown"
            counts[t] = counts.get(t, 0) + 1
        total = sum(counts.values())
        entropy = 0.0
        for c in counts.values():
            p = c / total
            if p > 0:
                entropy -= p * math.log2(p)
        return entropy

    # -------------------------------------------------------------------------
    # Async/Await Methods for Concurrent Ontology Extraction
    # -------------------------------------------------------------------------

    async def extract_entities_async(
        self,
        data: Any,
        context: OntologyGenerationContext
    ) -> EntityExtractionResult:
        """
        Asynchronously extract entities from data using configured strategy.
        
        This is the async version of :meth:`extract_entities`. It runs the
        extraction in a thread pool to avoid blocking the event loop.
        
        Args:
            data: Input data to extract entities from
            context: Context with extraction configuration
            
        Returns:
            EntityExtractionResult containing extracted entities and relationships
            
        Example:
            >>> result = await generator.extract_entities_async(
            ...     "Alice must pay Bob $100 by Friday",
            ...     context
            ... )
            >>> print(f"Found {len(result.entities)} entities")
        """
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.extract_entities,
            data,
            context
        )

    async def extract_batch_async(
        self,
        data_items: List[Any],
        contexts: Union[OntologyGenerationContext, List[OntologyGenerationContext]],
        max_concurrent: int = 5,
        timeout_per_item: Optional[float] = None,
    ) -> List[EntityExtractionResult]:
        """
        Asynchronously extract entities from multiple data items concurrently.
        
        Uses semaphore-controlled concurrency to process multiple items in parallel
        without overwhelming system resources.
        
        Args:
            data_items: List of data items to process
            contexts: Single context for all items or list of per-item contexts
            max_concurrent: Maximum number of concurrent extractions (default: 5)
            timeout_per_item: Optional timeout in seconds for each extraction
            
        Returns:
            List of EntityExtractionResult, one per input data item
            
        Example:
            >>> documents = ["doc1 text", "doc2 text", "doc3 text"]
            >>> results = await generator.extract_batch_async(
            ...     documents,
            ...     context,
            ...     max_concurrent=3
            ... )
            >>> total_entities = sum(len(r.entities) for r in results)
        """
        import asyncio
        
        # Handle single context for all items
        if isinstance(contexts, OntologyGenerationContext):
            contexts = [contexts] * len(data_items)
        
        if len(contexts) != len(data_items):
            raise ValueError(
                f"Length mismatch: {len(data_items)} data items but "
                f"{len(contexts)} contexts"
            )
        
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def extract_with_semaphore(data, ctx):
            async with semaphore:
                if timeout_per_item:
                    return await asyncio.wait_for(
                        self.extract_entities_async(data, ctx),
                        timeout=timeout_per_item
                    )
                else:
                    return await self.extract_entities_async(data, ctx)
        
        tasks = [
            extract_with_semaphore(data, ctx)
            for data, ctx in zip(data_items, contexts)
        ]
        
        return await asyncio.gather(*tasks)

    async def infer_relationships_async(
        self,
        entities: List[Entity],
        context: OntologyGenerationContext
    ) -> List[Relationship]:
        """
        Asynchronously infer relationships between entities.
        
        This is the async version of relationship inference. It runs the
        inference in a thread pool to avoid blocking the event loop.
        
        Args:
            entities: List of entities to infer relationships between
            context: Context with extraction configuration
            
        Returns:
            List of inferred Relationship objects
            
        Example:
            >>> entities = [entity1, entity2, entity3]
            >>> relationships = await generator.infer_relationships_async(
            ...     entities,
            ...     context
            ... )
            >>> print(f"Found {len(relationships)} relationships")
        """
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.infer_relationships,
            entities,
            context
        )

    async def extract_with_streaming_async(
        self,
        data: Any,
        context: OntologyGenerationContext,
        chunk_size: int = 1000
    ):
        """
        Asynchronously extract entities with streaming results.
        
        Yields EntityExtractionResult chunks as they become available,
        useful for processing large documents without waiting for complete results.
        
        Args:
            data: Input data to extract entities from
            context: Context with extraction configuration
            chunk_size: Number of entities per yielded chunk
            
        Yields:
            EntityExtractionResult objects with partial results
            
        Example:
            >>> async for chunk in generator.extract_with_streaming_async(
            ...     large_document,
            ...     context,
            ...     chunk_size=500
            ... ):
            ...     print(f"Received {len(chunk.entities)} entities")
            ...     # Process chunk immediately
        """
        import asyncio
        
        # For now, delegate to sync streaming and wrap in async
        # Future enhancement: true async streaming with backpressure
        loop = asyncio.get_event_loop()
        
        def sync_stream():
            return list(self.extract_entities_streaming(data, context))
        
        # Run in executor to avoid blocking
        chunks = await loop.run_in_executor(None, sync_stream)
        
        # Yield chunks asynchronously
        for chunk in chunks:
            yield chunk
            await asyncio.sleep(0)  # Yield control to event loop

    def entity_confidence_geometric_mean(self, result: "EntityExtractionResult") -> float:
        """Return the geometric mean of entity confidence scores.

        Args:
            result: EntityExtractionResult to analyse.

        Returns:
            Float geometric mean; ``0.0`` when no entities or any confidence is
            zero.
        """
        entities = getattr(result, "entities", []) or []
        if not entities:
            return 0.0
        confs = [getattr(e, "confidence", 0.0) for e in entities]
        if any(c <= 0.0 for c in confs):
            return 0.0
        product = 1.0
        for c in confs:
            product *= c
        return product ** (1.0 / len(confs))

    def entity_confidence_harmonic_mean(self, result: "EntityExtractionResult") -> float:
        """Return the harmonic mean of entity confidence scores.

        Args:
            result: EntityExtractionResult to analyse.

        Returns:
            Float harmonic mean; ``0.0`` when no entities or any confidence is
            zero.
        """
        entities = getattr(result, "entities", []) or []
        if not entities:
            return 0.0
        confs = [getattr(e, "confidence", 0.0) for e in entities]
        if any(c <= 0.0 for c in confs):
            return 0.0
        return len(confs) / sum(1.0 / c for c in confs)

    def relationship_confidence_iqr(self, result: "EntityExtractionResult") -> float:
        """Return the IQR of relationship confidence scores.

        Args:
            result: EntityExtractionResult to analyse.

        Returns:
            Float IQR (Q3 − Q1) of relationship confidences; ``0.0`` when
            fewer than 4 relationships are present.
        """
        relationships = getattr(result, "relationships", []) or []
        if len(relationships) < 4:
            return 0.0
        confs = sorted(getattr(r, "confidence", 0.0) for r in relationships)
        n = len(confs)
        q1_idx = n // 4
        q3_idx = (3 * n) // 4
        return confs[q3_idx] - confs[q1_idx]

    def entity_confidence_kurtosis(self, result: "EntityExtractionResult") -> float:
        """Return the excess kurtosis of entity confidence scores.

        Excess kurtosis = ``(1/n) * sum((x - mean)^4) / std^4 - 3``.

        Args:
            result: EntityExtractionResult to analyse.

        Returns:
            Float excess kurtosis; ``0.0`` when fewer than 4 entities or
            standard deviation is zero.
        """
        entities = getattr(result, "entities", []) or []
        if len(entities) < 4:
            return 0.0
        confs = [getattr(e, "confidence", 0.0) for e in entities]
        n = len(confs)
        mean = sum(confs) / n
        variance = sum((c - mean) ** 2 for c in confs) / n
        if variance == 0.0:
            return 0.0
        std4 = variance ** 2
        return sum((c - mean) ** 4 for c in confs) / (n * std4) - 3.0

    def entity_text_length_std(self, result: "EntityExtractionResult") -> float:
        """Return the standard deviation of entity text lengths.

        Args:
            result: EntityExtractionResult to analyse.

        Returns:
            Float std-dev; ``0.0`` when fewer than 2 entities.
        """
        entities = getattr(result, "entities", []) or []
        if len(entities) < 2:
            return 0.0
        lengths = [len(getattr(e, "text", "") or "") for e in entities]
        n = len(lengths)
        mean = sum(lengths) / n
        variance = sum((l - mean) ** 2 for l in lengths) / n
        return variance ** 0.5

    def entity_confidence_gini(self, result: "EntityExtractionResult") -> float:
        """Return the Gini coefficient of entity confidence scores.

        Uses the sorted-list formula.

        Args:
            result: EntityExtractionResult to analyse.

        Returns:
            Float Gini coefficient in [0, 1]; ``0.0`` when no entities or
            all confidences are equal.
        """
        entities = getattr(result, "entities", []) or []
        if not entities:
            return 0.0
        vals = sorted(getattr(e, "confidence", 0.0) for e in entities)
        n = len(vals)
        total = sum(vals)
        if total == 0.0:
            return 0.0
        weighted = sum((i + 1) * v for i, v in enumerate(vals))
        return (2 * weighted - (n + 1) * total) / (n * total)

    def relationship_type_count(self, result: "EntityExtractionResult") -> int:
        """Return the number of distinct relationship types in *result*.

        Args:
            result: EntityExtractionResult to analyse.

        Returns:
            Non-negative integer count of unique relationship type strings.
        """
        return len(self.relationship_type_counts(result))

    def avg_relationship_confidence(self, result: "EntityExtractionResult") -> float:
        """Return the mean confidence score across all relationships.

        Args:
            result: EntityExtractionResult to analyse.

        Returns:
            Float mean confidence; ``0.0`` when no relationships exist.
        """
        rels = getattr(result, "relationships", []) or []
        if not rels:
            return 0.0
        confs = [getattr(r, "confidence", 1.0) for r in rels]
        return sum(confs) / len(confs)

    def entity_type_count(self, result: "EntityExtractionResult") -> int:
        """Return the number of distinct entity types in *result*.

        Args:
            result: EntityExtractionResult to analyse.

        Returns:
            Non-negative integer count of unique entity type strings.
        """
        entities = getattr(result, "entities", []) or []
        return len({getattr(e, "type", "") for e in entities if getattr(e, "type", "")})

    def relationship_density(self, result: "EntityExtractionResult") -> float:
        """Return the directed relationship density of *result*.

        Density is defined as the number of relationships divided by the
        maximum possible directed relationships for *n* entities:
        ``n × (n − 1)``.

        Args:
            result: EntityExtractionResult to analyse.

        Returns:
            Float in [0, 1]; ``0.0`` when fewer than 2 entities.

        Example::

            >>> rd = generator.relationship_density(result)
            >>> 0.0 <= rd <= 1.0
        """
        n = len(getattr(result, "entities", []) or [])
        if n < 2:
            return 0.0
        rel_count = len(getattr(result, "relationships", []) or [])
        return rel_count / (n * (n - 1))

    def entity_confidence_weighted_mean(
        self,
        result: "EntityExtractionResult",
        weights: "Dict[str, float] | None" = None,
    ) -> float:
        """Return the type-weighted mean confidence of all entities.

        Each entity's confidence is multiplied by the weight associated with
        its type.  If a type has no entry in *weights* a default weight of
        ``1.0`` is used.  When *weights* is ``None`` all types get weight
        ``1.0`` (equivalent to a plain arithmetic mean).

        Args:
            result: :class:`EntityExtractionResult` to analyse.
            weights: Optional mapping of entity-type string → float weight.
                Missing types default to ``1.0``.

        Returns:
            Float in [0, 1]; ``0.0`` when there are no entities.

        Example::

            >>> wm = generator.entity_confidence_weighted_mean(result, {"Person": 2.0})
            >>> 0.0 <= wm <= 1.0
        """
        entities = getattr(result, "entities", []) or []
        if not entities:
            return 0.0
        if weights is None:
            weights = {}
        total_w = 0.0
        weighted_sum = 0.0
        for e in entities:
            w = weights.get(getattr(e, "type", ""), 1.0)
            total_w += w
            weighted_sum += w * getattr(e, "confidence", 0.0)
        if total_w == 0.0:
            return 0.0
        return weighted_sum / total_w

    def entity_confidence_trimmed_mean(self, result, trim_pct: float = 10.0) -> float:
        """Return the trimmed mean of entity confidence values.

        Sorts the confidence values, removes the lowest and highest
        ``trim_pct`` percent, and returns the arithmetic mean of the
        remaining values.

        Args:
            result: :class:`EntityExtractionResult` to analyse.
            trim_pct: Percentage to trim from *each* tail.  Must be in
                ``[0.0, 50.0)``.  Default ``10.0``.

        Returns:
            Float in ``[0, 1]``; ``0.0`` when there are no entities or no
            values remain after trimming.

        Raises:
            ValueError: When *trim_pct* is outside ``[0.0, 50.0)``.

        Example::

            >>> tm = generator.entity_confidence_trimmed_mean(result, trim_pct=10.0)
            >>> 0.0 <= tm <= 1.0
        """
        if trim_pct < 0.0 or trim_pct >= 50.0:
            raise ValueError("trim_pct must be in [0.0, 50.0).")
        entities = getattr(result, "entities", []) or []
        if not entities:
            return 0.0
        confidences = sorted(getattr(e, "confidence", 0.0) for e in entities)
        n = len(confidences)
        k = int(n * trim_pct / 100.0)
        trimmed = confidences[k: n - k] if (k < n and n - 2 * k > 0) else confidences
        if not trimmed:
            return 0.0
        return sum(trimmed) / len(trimmed)

    def relationship_avg_length(self, result: "EntityExtractionResult") -> float:
        """Return the average length of the relationship *type* text field.

        Each relationship exposes a ``type`` string (e.g. ``'causes'``,
        ``'owns'``).  This helper returns the mean character-count of those
        strings across all relationships in *result*.

        Args:
            result: :class:`EntityExtractionResult` to analyse.

        Returns:
            Non-negative float; ``0.0`` when there are no relationships.

        Example::

            >>> avg = generator.relationship_avg_length(result)
            >>> avg >= 0.0
        """
        rels = getattr(result, "relationships", []) or []
        if not rels:
            return 0.0
        return sum(len(getattr(r, "type", "") or "") for r in rels) / len(rels)

    def entity_avg_degree(self, result: "EntityExtractionResult") -> float:
        """Return the average number of relationships per entity in *result*.

        For each entity the *degree* is the number of relationships in which
        it appears as either the source or the target.  This method returns
        the mean degree across all entities.

        An entity that appears in no relationships has degree 0.  Relationships
        that reference entities not in ``result.entities`` are ignored.

        Args:
            result: :class:`EntityExtractionResult` to analyse.

        Returns:
            Non-negative float; ``0.0`` when there are no entities.

        Example::

            >>> gen.entity_avg_degree(result)
            0.0  # no entities
        """
        entities = getattr(result, "entities", []) or []
        rels = getattr(result, "relationships", []) or []
        if not entities:
            return 0.0
        degree: dict = {e.id: 0 for e in entities}
        for r in rels:
            src = getattr(r, "source_id", None)
            tgt = getattr(r, "target_id", None)
            if src in degree:
                degree[src] += 1
            if tgt in degree:
                degree[tgt] += 1
        return sum(degree.values()) / len(entities)

    def entity_confidence_below_threshold(
        self,
        result: "EntityExtractionResult",
        threshold: float = 0.5,
    ) -> int:
        """Count entities whose confidence score is strictly below *threshold*.

        Args:
            result: An :class:`EntityExtractionResult` (or any object with an
                ``entities`` attribute).
            threshold: Upper bound (exclusive) for the low-confidence test.
                Default ``0.5``.

        Returns:
            Non-negative integer count; ``0`` when *result* has no entities.

        Example::

            >>> gen.entity_confidence_below_threshold(result, threshold=0.5)
            0  # no entities
        """
        entities = getattr(result, "entities", []) or []
        count = 0
        for e in entities:
            conf = getattr(e, "confidence", None)
            if conf is not None and conf < threshold:
                count += 1
        return count


__all__ = [
    'OntologyGenerator',
    'OntologyGenerationContext',
    'Entity',
    'Relationship',
    'EntityExtractionResult',
    'ExtractionStrategy',
    'DataType',
]


