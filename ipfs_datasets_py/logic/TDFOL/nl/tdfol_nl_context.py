"""
TDFOL Context Resolver for Natural Language Processing

This module tracks context across sentences and resolves references
to maintain consistent entity identification in multi-sentence texts.

Features:
- Context tracking across sentences
- Reference resolution (pronouns, anaphora)
- Entity coreference handling
- Named entity management
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class Entity:
    """
    An entity tracked in the context.
    
    Represents a named entity (person, organization, etc.) that appears
    in the text and may be referred to multiple times.
    """
    
    name: str                           # Primary name
    type: str                           # Entity type (PERSON, ORG, etc.)
    aliases: Set[str] = field(default_factory=set)  # Alternative names
    mentions: List[str] = field(default_factory=list)  # All mentions
    sentence_ids: List[int] = field(default_factory=list)  # Sentences where mentioned
    metadata: Dict[str, any] = field(default_factory=dict)


@dataclass
class Context:
    """
    Context for tracking entities and references across sentences.
    
    Maintains a registry of entities and their mentions, enabling
    reference resolution for pronouns and repeated mentions.
    
    Example:
        >>> context = Context()
        >>> context.add_entity("contractor", "AGENT", sentence_id=0)
        >>> context.add_entity("contractor", "AGENT", sentence_id=1)
        >>> context.resolve_reference("they", sentence_id=1)
        'contractor'
    """
    
    entities: Dict[str, Entity] = field(default_factory=dict)
    current_sentence: int = 0
    last_mentioned: Optional[str] = None
    pronoun_refs: Dict[str, str] = field(default_factory=dict)
    
    def add_entity(
        self,
        name: str,
        entity_type: str,
        sentence_id: Optional[int] = None
    ) -> Entity:
        """
        Add or update an entity in the context.
        
        Args:
            name: Entity name
            entity_type: Type of entity (PERSON, ORG, AGENT, etc.)
            sentence_id: Sentence where entity appears
        
        Returns:
            The entity object
        """
        name_lower = name.lower()
        
        if name_lower in self.entities:
            entity = self.entities[name_lower]
            entity.mentions.append(name)
            if sentence_id is not None:
                entity.sentence_ids.append(sentence_id)
        else:
            entity = Entity(
                name=name,
                type=entity_type,
                aliases={name_lower},
                mentions=[name],
                sentence_ids=[sentence_id] if sentence_id is not None else []
            )
            self.entities[name_lower] = entity
        
        # Update last mentioned
        self.last_mentioned = name_lower
        
        return entity
    
    def resolve_reference(
        self,
        reference: str,
        sentence_id: Optional[int] = None
    ) -> Optional[str]:
        """
        Resolve a pronoun or reference to an entity.
        
        Args:
            reference: The reference to resolve (e.g., "they", "it", "the contractor")
            sentence_id: Current sentence ID
        
        Returns:
            The resolved entity name, or None if cannot resolve
        """
        ref_lower = reference.lower()
        
        # Check if it's a pronoun
        if ref_lower in ['he', 'she', 'they', 'it', 'him', 'her', 'them']:
            # Return last mentioned entity
            if self.last_mentioned:
                return self.entities[self.last_mentioned].name
            return None
        
        # Check if it's a definite description ("the contractor")
        if ref_lower.startswith('the '):
            base_name = ref_lower[4:]  # Remove "the "
            if base_name in self.entities:
                return self.entities[base_name].name
        
        # Check direct match
        if ref_lower in self.entities:
            return self.entities[ref_lower].name
        
        return None
    
    def get_entity(self, name: str) -> Optional[Entity]:
        """Get an entity by name."""
        return self.entities.get(name.lower())
    
    def list_entities(self) -> List[Entity]:
        """List all entities in context."""
        return list(self.entities.values())
    
    def clear(self):
        """Clear all context."""
        self.entities.clear()
        self.current_sentence = 0
        self.last_mentioned = None
        self.pronoun_refs.clear()


class ContextResolver:
    """
    Resolve references and maintain context across sentences.
    
    Tracks entities mentioned in text and resolves pronouns and
    repeated references to maintain consistent entity identification.
    
    Example:
        >>> from ipfs_datasets_py.logic.TDFOL.nl import (
        ...     NLPreprocessor,
        ...     PatternMatcher,
        ...     FormulaGenerator,
        ...     ContextResolver
        ... )
        >>> 
        >>> preprocessor = NLPreprocessor()
        >>> matcher = PatternMatcher()
        >>> generator = FormulaGenerator()
        >>> resolver = ContextResolver()
        >>> 
        >>> text = "Contractors must pay taxes. They shall file annually."
        >>> 
        >>> # Process first sentence
        >>> doc1 = preprocessor.process("Contractors must pay taxes.")
        >>> context = resolver.build_context(doc1)
        >>> 
        >>> # Process second sentence with context
        >>> doc2 = preprocessor.process("They shall file annually.")
        >>> resolver.resolve_references(doc2, context)
        >>> # "They" is resolved to "contractors"
    """
    
    def __init__(self):
        """Initialize context resolver."""
        pass
    
    def build_context(
        self,
        processed_doc: any,
        sentence_id: int = 0
    ) -> Context:
        """
        Build context from a processed document.
        
        Args:
            processed_doc: ProcessedDocument from NLPreprocessor
            sentence_id: Sentence ID for tracking
        
        Returns:
            Context object with extracted entities
        """
        context = Context()
        context.current_sentence = sentence_id
        
        # Extract entities from processed document
        if hasattr(processed_doc, 'entities'):
            for entity in processed_doc.entities:
                context.add_entity(
                    entity.text,
                    entity.type.value if hasattr(entity.type, 'value') else str(entity.type),
                    sentence_id=sentence_id
                )
        
        return context
    
    def update_context(
        self,
        context: Context,
        processed_doc: any,
        sentence_id: int
    ) -> Context:
        """
        Update existing context with new document.
        
        Args:
            context: Existing context
            processed_doc: New ProcessedDocument
            sentence_id: Sentence ID
        
        Returns:
            Updated context
        """
        context.current_sentence = sentence_id
        
        # Add new entities
        if hasattr(processed_doc, 'entities'):
            for entity in processed_doc.entities:
                context.add_entity(
                    entity.text,
                    entity.type.value if hasattr(entity.type, 'value') else str(entity.type),
                    sentence_id=sentence_id
                )
        
        return context
    
    def resolve_references(
        self,
        processed_doc: any,
        context: Context
    ) -> Dict[str, str]:
        """
        Resolve references in a processed document.
        
        Args:
            processed_doc: ProcessedDocument with potential references
            context: Context with known entities
        
        Returns:
            Dictionary mapping references to resolved entities
        """
        resolutions = {}
        
        # Check for pronouns in the text
        if hasattr(processed_doc, 'text'):
            text = processed_doc.text.lower()
            
            # Common pronouns
            pronouns = ['he', 'she', 'they', 'it', 'him', 'her', 'them']
            
            for pronoun in pronouns:
                if pronoun in text:
                    resolved = context.resolve_reference(pronoun)
                    if resolved:
                        resolutions[pronoun] = resolved
        
        return resolutions
    
    def merge_contexts(
        self,
        context1: Context,
        context2: Context
    ) -> Context:
        """
        Merge two contexts.
        
        Args:
            context1: First context
            context2: Second context
        
        Returns:
            Merged context
        """
        merged = Context()
        
        # Merge entities from both contexts
        for entity_name, entity in context1.entities.items():
            merged.entities[entity_name] = entity
        
        for entity_name, entity in context2.entities.items():
            if entity_name in merged.entities:
                # Merge mentions
                merged.entities[entity_name].mentions.extend(entity.mentions)
                merged.entities[entity_name].sentence_ids.extend(entity.sentence_ids)
                merged.entities[entity_name].aliases.update(entity.aliases)
            else:
                merged.entities[entity_name] = entity
        
        return merged
    
    def get_coreference_chains(
        self,
        context: Context
    ) -> List[List[str]]:
        """
        Get coreference chains from context.
        
        A coreference chain is a list of mentions that refer to the
        same entity.
        
        Args:
            context: Context with entities
        
        Returns:
            List of coreference chains (each chain is a list of mentions)
        """
        chains = []
        
        for entity in context.list_entities():
            if len(entity.mentions) > 1:
                chains.append(entity.mentions)
        
        return chains
