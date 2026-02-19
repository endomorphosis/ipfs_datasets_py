"""
Context Manager for DCEC Natural Language Processing.

This module provides context tracking and awareness for NL processing:
- Context state management
- Anaphora resolution (pronouns, references)
- Discourse context
- Entity tracking across utterances
"""

from typing import List, Dict, Optional, Set, Any
from dataclasses import dataclass, field
from enum import Enum
import logging

try:
    from beartype import beartype
except ImportError:
    from typing import TypeVar, Callable
    F = TypeVar('F', bound=Callable[..., Any])
    def beartype(func: F) -> F:
        return func

logger = logging.getLogger(__name__)


class EntityType(Enum):
    """Types of entities in context."""
    AGENT = "agent"
    OBJECT = "object"
    EVENT = "event"
    TIME = "time"
    LOCATION = "location"
    PROPERTY = "property"


@dataclass
class Entity:
    """An entity in the discourse context.
    
    Attributes:
        name: Entity identifier
        entity_type: Type of entity
        properties: Entity properties
        mentions: List of mentions (positions in discourse)
    """
    name: str
    entity_type: EntityType
    properties: Dict[str, Any] = field(default_factory=dict)
    mentions: List[int] = field(default_factory=list)
    
    def add_mention(self, position: int):
        """Add a mention of this entity.
        
        Args:
            position: Position in discourse
        """
        self.mentions.append(position)
    
    def most_recent_mention(self) -> Optional[int]:
        """Get most recent mention position."""
        if not self.mentions:
            return None
        return max(self.mentions)


@dataclass
class ContextState:
    """State of the discourse context.
    
    Attributes:
        entities: Active entities
        focus: Currently focused entity
        discourse_history: History of utterances
        position: Current position in discourse
    """
    entities: Dict[str, Entity] = field(default_factory=dict)
    focus: Optional[Entity] = None
    discourse_history: List[str] = field(default_factory=list)
    position: int = 0
    
    def add_entity(self, entity: Entity):
        """Add an entity to the context.
        
        Args:
            entity: Entity to add
        """
        self.entities[entity.name] = entity
    
    def get_entity(self, name: str) -> Optional[Entity]:
        """Get entity by name.
        
        Args:
            name: Entity name
            
        Returns:
            Entity or None if not found
        """
        return self.entities.get(name)
    
    def set_focus(self, entity: Entity):
        """Set the discourse focus.
        
        Args:
            entity: Entity to focus on
        """
        self.focus = entity
    
    def add_utterance(self, utterance: str):
        """Add an utterance to history.
        
        Args:
            utterance: Utterance text
        """
        self.discourse_history.append(utterance)
        self.position += 1


class ContextManager:
    """Manages discourse context and anaphora resolution."""
    
    def __init__(self):
        """Initialize context manager."""
        self.state = ContextState()
        self.pronoun_mappings: Dict[str, EntityType] = {
            "he": EntityType.AGENT,
            "she": EntityType.AGENT,
            "it": EntityType.OBJECT,
            "they": EntityType.AGENT,
        }
    
    @beartype
    def process_utterance(self, utterance: str) -> ContextState:
        """Process an utterance and update context.
        
        Args:
            utterance: Input utterance
            
        Returns:
            Updated context state
        """
        # Add to history
        self.state.add_utterance(utterance)
        
        # Extract entities from utterance
        entities = self._extract_entities(utterance)
        for entity in entities:
            entity.add_mention(self.state.position)
            self.state.add_entity(entity)
            
            # Update focus to most recent entity
            self.state.set_focus(entity)
        
        # Resolve any pronouns
        resolved = self._resolve_pronouns(utterance)
        
        return self.state
    
    def _extract_entities(self, utterance: str) -> List[Entity]:
        """Extract entities from utterance.
        
        Args:
            utterance: Input text
            
        Returns:
            List of entities found
        """
        entities = []
        words = utterance.lower().split()
        
        # Simple entity extraction (would be more sophisticated in practice)
        agent_indicators = {"alice", "bob", "charlie", "agent", "person"}
        object_indicators = {"door", "light", "window", "object"}
        
        for word in words:
            if word in agent_indicators:
                entity = Entity(word, EntityType.AGENT)
                entities.append(entity)
            elif word in object_indicators:
                entity = Entity(word, EntityType.OBJECT)
                entities.append(entity)
        
        return entities
    
    def _resolve_pronouns(self, utterance: str) -> Dict[str, Entity]:
        """Resolve pronouns to entities.
        
        Args:
            utterance: Input text
            
        Returns:
            Mapping from pronouns to resolved entities
        """
        resolution = {}
        words = utterance.lower().split()
        
        for word in words:
            if word in self.pronoun_mappings:
                # Resolve to focused entity or most recent of matching type
                entity_type = self.pronoun_mappings[word]
                resolved = self._find_antecedent(entity_type)
                if resolved:
                    resolution[word] = resolved
        
        return resolution
    
    def _find_antecedent(self, entity_type: EntityType) -> Optional[Entity]:
        """Find antecedent for anaphora resolution.
        
        Args:
            entity_type: Type of entity to find
            
        Returns:
            Most appropriate entity or None
        """
        # First check focus
        if self.state.focus and self.state.focus.entity_type == entity_type:
            return self.state.focus
        
        # Find most recently mentioned entity of matching type
        candidates = [
            e for e in self.state.entities.values()
            if e.entity_type == entity_type and e.mentions
        ]
        
        if not candidates:
            return None
        
        # Return most recently mentioned
        return max(candidates, key=lambda e: e.most_recent_mention())
    
    @beartype
    def resolve_reference(self, reference: str) -> Optional[Entity]:
        """Resolve a reference to an entity.
        
        Args:
            reference: Reference string (name or pronoun)
            
        Returns:
            Resolved entity or None
        """
        ref_lower = reference.lower()
        
        # Check if it's a direct entity reference
        if ref_lower in self.state.entities:
            return self.state.entities[ref_lower]
        
        # Check if it's a pronoun
        if ref_lower in self.pronoun_mappings:
            entity_type = self.pronoun_mappings[ref_lower]
            return self._find_antecedent(entity_type)
        
        return None
    
    def get_context_state(self) -> ContextState:
        """Get current context state.
        
        Returns:
            Current context state
        """
        return self.state
    
    def reset_context(self):
        """Reset the context to initial state."""
        self.state = ContextState()
    
    def get_discourse_history(self) -> List[str]:
        """Get discourse history.
        
        Returns:
            List of previous utterances
        """
        return self.state.discourse_history.copy()
    
    def get_active_entities(self) -> List[Entity]:
        """Get all active entities.
        
        Returns:
            List of entities in context
        """
        return list(self.state.entities.values())
    
    def get_focused_entity(self) -> Optional[Entity]:
        """Get currently focused entity.
        
        Returns:
            Focused entity or None
        """
        return self.state.focus


class AnaphoraResolver:
    """Specialized resolver for anaphoric references."""
    
    def __init__(self, context_manager: ContextManager):
        """Initialize anaphora resolver.
        
        Args:
            context_manager: Context manager to use
        """
        self.context_manager = context_manager
        self.resolution_history: List[Dict[str, Entity]] = []
    
    @beartype
    def resolve_anaphora(self, text: str) -> Dict[str, Entity]:
        """Resolve all anaphoric references in text.
        
        Args:
            text: Input text
            
        Returns:
            Mapping from anaphors to resolved entities
        """
        resolutions = {}
        words = text.lower().split()
        
        anaphors = {"he", "she", "it", "they", "this", "that"}
        
        for word in words:
            if word in anaphors:
                # Determine entity type
                if word in {"he", "she", "they"}:
                    entity_type = EntityType.AGENT
                else:
                    entity_type = EntityType.OBJECT
                
                # Find antecedent
                entity = self.context_manager._find_antecedent(entity_type)
                if entity:
                    resolutions[word] = entity
        
        self.resolution_history.append(resolutions)
        return resolutions
    
    def get_resolution_history(self) -> List[Dict[str, Entity]]:
        """Get history of resolutions.
        
        Returns:
            List of resolution mappings
        """
        return self.resolution_history.copy()


class DiscourseAnalyzer:
    """Analyzes discourse structure and coherence."""
    
    def __init__(self):
        """Initialize discourse analyzer."""
        self.segments: List[List[str]] = []
    
    @beartype
    def segment_discourse(self, utterances: List[str]) -> List[List[str]]:
        """Segment discourse into coherent segments.
        
        Args:
            utterances: List of utterances
            
        Returns:
            List of discourse segments
        """
        if not utterances:
            return []
        
        segments = []
        current_segment = [utterances[0]]
        
        for i in range(1, len(utterances)):
            # Simple segmentation: new segment on topic shift
            # (would use more sophisticated methods in practice)
            if self._is_topic_shift(utterances[i-1], utterances[i]):
                segments.append(current_segment)
                current_segment = [utterances[i]]
            else:
                current_segment.append(utterances[i])
        
        if current_segment:
            segments.append(current_segment)
        
        self.segments = segments
        return segments
    
    def _is_topic_shift(self, utt1: str, utt2: str) -> bool:
        """Detect topic shift between utterances.
        
        Args:
            utt1: First utterance
            utt2: Second utterance
            
        Returns:
            True if topic shift detected
        """
        # Simple heuristic: check for discourse markers
        shift_markers = {"however", "but", "meanwhile", "next", "then"}
        words2 = utt2.lower().split()
        return any(marker in words2 for marker in shift_markers)
    
    @beartype
    def analyze_coherence(self, utterances: List[str]) -> float:
        """Analyze discourse coherence.
        
        Args:
            utterances: List of utterances
            
        Returns:
            Coherence score [0, 1]
        """
        if len(utterances) < 2:
            return 1.0
        
        # Simple coherence measure: overlap in content words
        total_overlap = 0
        
        for i in range(len(utterances) - 1):
            words1 = set(utterances[i].lower().split())
            words2 = set(utterances[i+1].lower().split())
            overlap = len(words1 & words2)
            total_overlap += overlap
        
        # Normalize by number of pairs
        avg_overlap = total_overlap / (len(utterances) - 1)
        
        # Convert to [0, 1] score
        return min(1.0, avg_overlap / 3.0)
