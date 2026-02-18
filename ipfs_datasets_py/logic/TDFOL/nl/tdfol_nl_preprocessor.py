"""
Natural Language Preprocessor for TDFOL

This module provides preprocessing capabilities for natural language text,
including sentence splitting, entity recognition, dependency parsing, and
temporal expression normalization.

Requires spaCy: pip install ipfs_datasets_py[knowledge_graphs]
After installation, download the English model:
    python -m spacy download en_core_web_sm
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Import spaCy from centralized utils
from .spacy_utils import HAVE_SPACY, spacy, Doc, Token


class EntityType(Enum):
    """Types of entities extracted from natural language."""
    
    AGENT = "agent"          # Persons, organizations acting (contractors, Alice)
    ACTION = "action"        # Verbs, activities (pay, deliver, comply)
    OBJECT = "object"        # Things acted upon (taxes, documents, goods)
    TIME = "time"            # Temporal expressions (within 30 days, always)
    CONDITION = "condition"  # Conditional phrases (if paid, when delivered)
    MODALITY = "modality"    # Modal expressions (must, may, shall, forbidden)
    UNKNOWN = "unknown"


@dataclass
class Entity:
    """Extracted entity from natural language text."""
    
    text: str                    # Original text span
    type: EntityType             # Entity type
    start: int                   # Start character position
    end: int                     # End character position
    lemma: Optional[str] = None  # Lemmatized form
    metadata: Dict[str, Any] = field(default_factory=dict)  # Additional metadata
    
    def __hash__(self) -> int:
        return hash((self.text, self.type, self.start, self.end))


@dataclass
class TemporalExpression:
    """Temporal expression extracted from text."""
    
    text: str                    # Original text
    type: str                    # Type: deadline, duration, frequency, point
    value: Optional[str] = None  # Normalized value (e.g., "30 days")
    start: int = 0
    end: int = 0


@dataclass
class DependencyRelation:
    """Dependency relation between tokens."""
    
    head: str      # Head token
    dependent: str # Dependent token
    relation: str  # Dependency relation type (nsubj, dobj, etc.)


@dataclass
class ProcessedDocument:
    """Result of preprocessing a natural language document."""
    
    text: str                                    # Original text
    sentences: List[str]                         # Sentence-split text
    entities: List[Entity]                       # Extracted entities
    temporal: List[TemporalExpression]           # Temporal expressions
    modalities: List[str]                        # Modal expressions (must, may, etc.)
    dependencies: List[DependencyRelation]       # Dependency relations
    spacy_doc: Optional[Any] = None              # Original spaCy Doc object
    metadata: Dict[str, Any] = field(default_factory=dict)  # Additional metadata


class NLPreprocessor:
    """
    Natural language preprocessor for TDFOL.
    
    Provides:
    - Sentence splitting
    - Entity recognition (agents, actions, objects)
    - Dependency parsing (subject-verb-object relations)
    - Temporal expression normalization
    - Modal verb identification
    
    Example:
        >>> preprocessor = NLPreprocessor()
        >>> doc = preprocessor.process("All contractors must pay taxes within 30 days.")
        >>> print(doc.entities)
        [Entity(text='contractors', type=EntityType.AGENT, ...)]
        >>> print(doc.modalities)
        ['must']
    """
    
    def __init__(self, model: str = "en_core_web_sm"):
        """
        Initialize NL preprocessor.
        
        Args:
            model: spaCy model name (default: en_core_web_sm)
        
        Raises:
            ImportError: If spaCy is not installed
            OSError: If spaCy model is not downloaded
        """
        if not HAVE_SPACY:
            raise ImportError(
                "spaCy is required for natural language processing. "
                "Install with: pip install ipfs_datasets_py[knowledge_graphs]"
            )
        
        try:
            self.nlp = spacy.load(model)
        except OSError:
            logger.error(f"spaCy model '{model}' not found. Download with: python -m spacy download {model}")
            raise
        
        # Patterns for temporal expressions
        self.temporal_patterns = [
            (r'within\s+(\d+)\s+(day|week|month|year)s?', 'deadline'),
            (r'after\s+(\d+)\s+(day|week|month|year)s?', 'deadline'),
            (r'before\s+(\d+)\s+(day|week|month|year)s?', 'deadline'),
            (r'for\s+(\d+)\s+(day|week|month|year)s?', 'duration'),
            (r'every\s+(\d+)\s+(day|week|month|year)s?', 'frequency'),
        ]
        
        # Modal verbs and expressions
        self.modal_expressions = {
            'must', 'shall', 'should', 'may', 'can', 'could', 'would',
            'must not', 'shall not', 'should not', 'may not', 'cannot',
            'required to', 'obligated to', 'permitted to', 'allowed to',
            'forbidden to', 'prohibited from'
        }
    
    def process(self, text: str) -> ProcessedDocument:
        """
        Process natural language text.
        
        Args:
            text: Input text to process
        
        Returns:
            ProcessedDocument with extracted entities and metadata
        """
        # Run spaCy pipeline
        doc = self.nlp(text)
        
        # Extract components
        sentences = self._extract_sentences(doc)
        entities = self._extract_entities(doc)
        temporal = self._extract_temporal_expressions(text)
        modalities = self._extract_modalities(doc)
        dependencies = self._extract_dependencies(doc)
        
        return ProcessedDocument(
            text=text,
            sentences=sentences,
            entities=entities,
            temporal=temporal,
            modalities=modalities,
            dependencies=dependencies,
            spacy_doc=doc,
            metadata={
                'num_sentences': len(sentences),
                'num_entities': len(entities),
                'num_temporal': len(temporal),
            }
        )
    
    def _extract_sentences(self, doc: Doc) -> List[str]:
        """Extract sentences from document."""
        return [sent.text.strip() for sent in doc.sents]
    
    def _extract_entities(self, doc: Doc) -> List[Entity]:
        """
        Extract entities from document.
        
        Identifies:
        - Agents (PERSON, ORG, NORP)
        - Actions (VERB roots)
        - Objects (direct objects, noun phrases)
        - Time expressions (DATE, TIME)
        """
        entities = []
        
        # Named entities from spaCy NER
        for ent in doc.ents:
            entity_type = EntityType.UNKNOWN
            if ent.label_ in ['PERSON', 'ORG', 'NORP', 'GPE']:
                entity_type = EntityType.AGENT
            elif ent.label_ in ['DATE', 'TIME']:
                entity_type = EntityType.TIME
            
            entities.append(Entity(
                text=ent.text,
                type=entity_type,
                start=ent.start_char,
                end=ent.end_char,
                lemma=ent.lemma_,
                metadata={'label': ent.label_}
            ))
        
        # Extract actions (main verbs)
        for token in doc:
            if token.pos_ == 'VERB' and token.dep_ in ['ROOT', 'xcomp', 'ccomp']:
                entities.append(Entity(
                    text=token.text,
                    type=EntityType.ACTION,
                    start=token.idx,
                    end=token.idx + len(token.text),
                    lemma=token.lemma_,
                    metadata={'pos': token.pos_, 'dep': token.dep_}
                ))
        
        # Extract agents from noun subjects
        for token in doc:
            if token.dep_ in ['nsubj', 'nsubjpass'] and token.pos_ in ['NOUN', 'PROPN']:
                # Check if not already captured
                if not any(e.text == token.text and e.type == EntityType.AGENT for e in entities):
                    entities.append(Entity(
                        text=token.text,
                        type=EntityType.AGENT,
                        start=token.idx,
                        end=token.idx + len(token.text),
                        lemma=token.lemma_,
                        metadata={'pos': token.pos_, 'dep': token.dep_}
                    ))
        
        # Extract objects from direct/indirect objects
        for token in doc:
            if token.dep_ in ['dobj', 'iobj', 'pobj'] and token.pos_ in ['NOUN', 'PROPN']:
                entities.append(Entity(
                    text=token.text,
                    type=EntityType.OBJECT,
                    start=token.idx,
                    end=token.idx + len(token.text),
                    lemma=token.lemma_,
                    metadata={'pos': token.pos_, 'dep': token.dep_}
                ))
        
        return entities
    
    def _extract_temporal_expressions(self, text: str) -> List[TemporalExpression]:
        """Extract and normalize temporal expressions."""
        temporal = []
        
        for pattern, expr_type in self.temporal_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                temporal.append(TemporalExpression(
                    text=match.group(0),
                    type=expr_type,
                    value=f"{match.group(1)} {match.group(2)}{'s' if int(match.group(1)) > 1 else ''}",
                    start=match.start(),
                    end=match.end()
                ))
        
        # Common temporal adverbs
        temporal_adverbs = ['always', 'never', 'sometimes', 'eventually', 'immediately']
        for adverb in temporal_adverbs:
            for match in re.finditer(r'\b' + adverb + r'\b', text, re.IGNORECASE):
                temporal.append(TemporalExpression(
                    text=match.group(0),
                    type='adverb',
                    value=adverb.lower(),
                    start=match.start(),
                    end=match.end()
                ))
        
        return temporal
    
    def _extract_modalities(self, doc: Doc) -> List[str]:
        """Extract modal expressions (must, may, shall, etc.)."""
        modalities = []
        
        # Check for modal auxiliaries
        for token in doc:
            if token.pos_ == 'AUX' and token.text.lower() in self.modal_expressions:
                modalities.append(token.text.lower())
        
        # Check for modal expressions (multi-word)
        text_lower = doc.text.lower()
        for modal_expr in self.modal_expressions:
            if len(modal_expr.split()) > 1 and modal_expr in text_lower:
                if modal_expr not in modalities:
                    modalities.append(modal_expr)
        
        return list(set(modalities))  # Remove duplicates
    
    def _extract_dependencies(self, doc: Doc) -> List[DependencyRelation]:
        """Extract dependency relations between tokens."""
        dependencies = []
        
        for token in doc:
            if token.dep_ != 'ROOT' and token.head != token:
                dependencies.append(DependencyRelation(
                    head=token.head.text,
                    dependent=token.text,
                    relation=token.dep_
                ))
        
        return dependencies
    
    def extract_agents_actions_objects(self, doc: ProcessedDocument) -> Tuple[List[Entity], List[Entity], List[Entity]]:
        """
        Extract agents, actions, and objects separately.
        
        Returns:
            Tuple of (agents, actions, objects) entity lists
        """
        agents = [e for e in doc.entities if e.type == EntityType.AGENT]
        actions = [e for e in doc.entities if e.type == EntityType.ACTION]
        objects = [e for e in doc.entities if e.type == EntityType.OBJECT]
        
        return agents, actions, objects
