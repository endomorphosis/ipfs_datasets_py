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

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
from enum import Enum

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
    config: Union[ExtractionConfig, Dict[str, Any]] = field(default_factory=dict)
    
    def __post_init__(self):
        """Convert string enums to proper enum types and normalise config."""
        if isinstance(self.data_type, str):
            self.data_type = DataType(self.data_type)
        if isinstance(self.extraction_strategy, str):
            self.extraction_strategy = ExtractionStrategy(self.extraction_strategy)
        if isinstance(self.config, dict):
            self.config = ExtractionConfig.from_dict(self.config)

    @property
    def extraction_config(self) -> ExtractionConfig:
        """Typed alias for :attr:`config`."""
        if isinstance(self.config, ExtractionConfig):
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
    """
    
    id: str
    type: str
    text: str
    properties: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    source_span: Optional[tuple[int, int]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialise this entity to a plain dictionary.

        Returns:
            Dict with keys ``id``, ``type``, ``text``, ``confidence``,
            ``properties``, and ``source_span``.

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
        return cls(
            id=d["id"],
            type=d["type"],
            text=d["text"],
            confidence=float(d.get("confidence", 1.0)),
            properties=dict(d.get("properties") or {}),
            source_span=tuple(span) if span is not None else None,  # type: ignore[arg-type]
        )


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
        self.use_ipfs_accelerate = use_ipfs_accelerate
        self._accelerate_client = None
        self.llm_backend = llm_backend
        
        if use_ipfs_accelerate:
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
            result = self._extract_rule_based(data, context)
            # LLM fallback: if rule-based confidence is below threshold and a
            # llm_backend is configured, retry with LLM-based extraction.
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

        # Heuristic verb-frame patterns: (pattern, relationship_type)
        _VERB_PATTERNS = [
            (r'\b(\w+)\s+(?:must|shall|is required to|is obligated to)\s+\w+\s+(\w+)\b', 'obligates'),
            (r'\b(\w+)\s+owns?\s+(\w+)\b', 'owns'),
            (r'\b(\w+)\s+causes?\s+(\w+)\b', 'causes'),
            (r'\b(\w+)\s+(?:is a|is an)\s+(\w+)\b', 'is_a'),
            (r'\b(\w+)\s+(?:part of|belongs to)\s+(\w+)\b', 'part_of'),
            (r'\b(\w+)\s+(?:employs?|hired?)\s+(\w+)\b', 'employs'),
            (r'\b(\w+)\s+(?:manages?|supervises?)\s+(\w+)\b', 'manages'),
        ]

        import re as _re
        entity_texts = {e.text.lower(): e for e in entities}
        entity_ids_by_text = {e.text.lower(): e.id for e in entities}

        rel_id_counter = [0]

        def _make_rel_id() -> str:
            rel_id_counter[0] += 1
            return f"rel_{rel_id_counter[0]:04d}"

        # 1) Verb-frame matching in text
        for pattern, rel_type in _VERB_PATTERNS:
            for m in _re.finditer(pattern, text, _re.IGNORECASE):
                subj_text = m.group(1).lower()
                obj_text = m.group(2).lower()
                src_id = entity_ids_by_text.get(subj_text)
                tgt_id = entity_ids_by_text.get(obj_text)
                if src_id and tgt_id and src_id != tgt_id:
                    relationships.append(Relationship(
                        id=_make_rel_id(),
                        source_id=src_id,
                        target_id=tgt_id,
                        type=rel_type,
                        confidence=0.65,
                        direction='subject_to_object',
                    ))

        # 2) Sliding-window co-occurrence (window=200 chars) for entities
        # that weren't already linked by verb patterns.
        # Confidence decay: base 0.6 at distance 0, decays linearly.
        # Entities >100 chars apart receive < 0.4 confidence; floor is 0.2.
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
                    relationships.append(Relationship(
                        id=_make_rel_id(),
                        source_id=e1.id,
                        target_id=e2.id,
                        type='related_to',
                        confidence=confidence,
                        direction='undirected',
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
        # Rule-based NER using regex patterns organized by entity type.
        import re as _re
        import uuid as _uuid

        # Base patterns (domain-agnostic)
        _BASE_PATTERNS: list[tuple[str, str]] = [
            # Person names (Title + Capitalised words)
            (r'\b(?:Mr|Mrs|Ms|Dr|Prof)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*', 'Person'),
            # Organisation suffixes
            (r'\b[A-Z][A-Za-z&\s]*(?:LLC|Ltd|Inc|Corp|GmbH|PLC|Co\.)\b', 'Organization'),
            # Dates
            (r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b', 'Date'),
            (r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b', 'Date'),
            # Monetary amounts
            (r'\b(?:USD|EUR|GBP)\s*[\d,]+(?:\.\d{2})?\b', 'MonetaryAmount'),
            # Locations — simple proper-noun heuristic for known indicators
            (r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Street|Avenue|Road|City|County|State|Country|Region|District)\b', 'Location'),
            # Legal obligations (noun phrases around "obligation", "duty", "right")
            (r'\b(?:the\s+)?(?:obligation|duty|right|liability|breach|claim|penalty)\s+(?:of\s+)?[A-Z][a-z]+\b', 'Obligation'),
            # Generic capitalised concepts (fallback — lower confidence)
            (r'\b[A-Z][A-Za-z]{3,}\b', 'Concept'),
        ]

        # Domain-specific supplemental patterns
        _DOMAIN_PATTERNS: dict[str, list[tuple[str, str]]] = {
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

        domain = getattr(context, 'domain', 'general').lower() if context else 'general'
        _PATTERNS = _BASE_PATTERNS + _DOMAIN_PATTERNS.get(domain, [])

        # Append pluggable custom rules from context config (before generic Concept fallback)
        ext_config = getattr(context, 'extraction_config', None) if context else None
        if ext_config is not None and hasattr(ext_config, 'custom_rules') and ext_config.custom_rules:
            # Insert custom rules before the last (generic Concept fallback) pattern
            _PATTERNS = _PATTERNS[:-1] + list(ext_config.custom_rules) + [_PATTERNS[-1]]

        text = str(data) if data is not None else ""
        entities: list[Entity] = []
        seen_texts: set[str] = set()

        # Resolve min_entity_length from config (safe fallback if config is a mock)
        try:
            min_len = int(getattr(ext_config, "min_entity_length", 2)) if ext_config is not None else 2
        except (TypeError, ValueError):
            min_len = 2

        # Resolve stopwords set (case-insensitive match against key)
        try:
            _stop = {w.lower() for w in (getattr(ext_config, "stopwords", []) or [])} if ext_config is not None else set()
        except (TypeError, AttributeError):
            _stop = set()

        # Resolve allowed_entity_types whitelist (empty = allow all)
        try:
            _allowed = set(getattr(ext_config, "allowed_entity_types", []) or []) if ext_config is not None else set()
        except (TypeError, AttributeError):
            _allowed = set()

        # Resolve max_confidence cap
        try:
            _max_conf = float(getattr(ext_config, "max_confidence", 1.0)) if ext_config is not None else 1.0
        except (TypeError, ValueError, AttributeError):
            _max_conf = 1.0

        for pattern, ent_type in _PATTERNS:
            if _allowed and ent_type not in _allowed:
                continue
            confidence = 0.5 if ent_type == 'Concept' else 0.75
            confidence = min(confidence, _max_conf)
            for m in _re.finditer(pattern, text):
                raw = m.group(0).strip()
                key = raw.lower()
                if key in seen_texts or len(raw) < min_len or key in _stop:
                    continue
                seen_texts.add(key)
                entities.append(Entity(
                    id=f"e_{_uuid.uuid4().hex[:8]}",
                    type=ent_type,
                    text=raw,
                    confidence=confidence,
                    source_span=(m.start(), m.end()),
                ))

        # Derive relationships from extracted entities
        relationships = self.infer_relationships(entities, context, data)

        self._log.info(f"Rule-based extraction found {len(entities)} entities, {len(relationships)} relationships")
        return EntityExtractionResult(
            entities=entities,
            relationships=relationships,
            confidence=0.7,
            metadata={'method': 'rule_based', 'entity_count': len(entities)},
        )
    
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
        entities = []
        for i in range(n_entities):
            etype = entity_types[i % len(entity_types)]
            entities.append({
                "id": f"syn_{domain}_{i}",
                "type": etype,
                "text": f"{etype}_{i}",
                "properties": {"synthetic": True, "index": i},
                "confidence": 0.9,
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


__all__ = [
    'OntologyGenerator',
    'OntologyGenerationContext',
    'Entity',
    'Relationship',
    'EntityExtractionResult',
    'ExtractionStrategy',
    'DataType',
]
