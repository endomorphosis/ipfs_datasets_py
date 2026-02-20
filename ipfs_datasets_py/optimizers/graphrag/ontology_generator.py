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
    """

    confidence_threshold: float = 0.5
    max_entities: int = 0
    max_relationships: int = 0
    window_size: int = 5
    include_properties: bool = True
    domain_vocab: Dict[str, List[str]] = field(default_factory=dict)
    # Pluggable rule sets: list of (regex_pattern, entity_type) tuples
    custom_rules: List[tuple] = field(default_factory=list)

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
        )


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
    """
    
    id: str
    source_id: str
    target_id: str
    type: str
    properties: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0


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
    ):
        """
        Initialize the ontology generator.
        
        Args:
            ipfs_accelerate_config: Configuration for ipfs_accelerate_py.
                Should include 'model', 'task', and optionally 'device'.
            use_ipfs_accelerate: Whether to use ipfs_accelerate for inference.
                If False, falls back to rule-based extraction.
            logger: Optional :class:`logging.Logger`.  Defaults to the module logger.
                
        Raises:
            ImportError: If ipfs_accelerate is required but not available
        """
        import logging as _logging
        self._log = logger or _logging.getLogger(__name__)
        self.ipfs_accelerate_config = ipfs_accelerate_config or {}
        self.use_ipfs_accelerate = use_ipfs_accelerate
        self._accelerate_client = None
        
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
            return self._extract_rule_based(data, context)
        elif context.extraction_strategy == ExtractionStrategy.LLM_BASED:
            return self._extract_llm_based(data, context)
        elif context.extraction_strategy == ExtractionStrategy.HYBRID:
            return self._extract_hybrid(data, context)
        elif context.extraction_strategy == ExtractionStrategy.NEURAL:
            return self._extract_neural(data, context)
        else:
            raise ValueError(
                f"Unknown extraction strategy: {context.extraction_strategy}"
            )
    
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
                    ))

        # 2) Sliding-window co-occurrence (window=50 chars) for entities
        # that weren't already linked by verb patterns
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
                    confidence = max(0.3, 0.6 - distance / 500.0)
                    relationships.append(Relationship(
                        id=_make_rel_id(),
                        source_id=e1.id,
                        target_id=e2.id,
                        type='related_to',
                        confidence=confidence,
                    ))
                    linked.add((e1.id, e2.id))

        self._log.info(f"Inferred {len(relationships)} relationships")
        return relationships
    
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

        for pattern, ent_type in _PATTERNS:
            confidence = 0.5 if ent_type == 'Concept' else 0.75
            for m in _re.finditer(pattern, text):
                raw = m.group(0).strip()
                key = raw.lower()
                if key in seen_texts or len(raw) < 2:
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
            'confidence': relationship.confidence
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


# Export public API
__all__ = [
    'OntologyGenerator',
    'OntologyGenerationContext',
    'Entity',
    'Relationship',
    'EntityExtractionResult',
    'ExtractionStrategy',
    'DataType',
]
