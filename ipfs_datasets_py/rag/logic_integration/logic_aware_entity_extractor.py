"""Logic-aware entity extraction for GraphRAG.

This module provides intelligent extraction of logical entities from text,
enabling GraphRAG to understand deontic logic (obligations, permissions,
prohibitions), temporal constraints, and conditional relationships.
"""

from typing import List, Dict, Tuple, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
import re


class LogicalEntityType(Enum):
    """Types of logical entities that can be extracted from text."""
    
    AGENT = "agent"  # e.g., "Alice", "Bob", "Company A"
    PREDICATE = "predicate"  # e.g., "owns", "pays", "delivers"
    OBLIGATION = "obligation"  # e.g., "must pay", "shall deliver"
    PERMISSION = "permission"  # e.g., "may access", "can modify"
    PROHIBITION = "prohibition"  # e.g., "forbidden to", "must not"
    TEMPORAL_CONSTRAINT = "temporal"  # e.g., "within 30 days", "always"
    CONDITIONAL = "conditional"  # e.g., "if... then..."


@dataclass
class LogicalEntity:
    """A logical entity extracted from text.
    
    Attributes:
        text: The text of the entity
        entity_type: Type of logical entity
        confidence: Confidence score (0-1)
        formula: Optional TDFOL formula representation
        metadata: Additional metadata (position, context, etc.)
    """
    
    text: str
    entity_type: LogicalEntityType
    confidence: float
    formula: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate confidence is in valid range."""
        if not 0 <= self.confidence <= 1:
            raise ValueError(f"Confidence must be between 0 and 1, got {self.confidence}")


@dataclass
class LogicalRelationship:
    """A logical relationship between entities.
    
    Attributes:
        source: Source entity
        target: Target entity
        relation_type: Type of relationship
        confidence: Confidence score (0-1)
        formula: Optional TDFOL formula representation
    """
    
    source: LogicalEntity
    target: LogicalEntity
    relation_type: str
    confidence: float
    formula: Optional[Any] = None
    
    def __post_init__(self):
        """Validate confidence is in valid range."""
        if not 0 <= self.confidence <= 1:
            raise ValueError(f"Confidence must be between 0 and 1, got {self.confidence}")


class LogicAwareEntityExtractor:
    """Extract logical entities from text using pattern matching and optional neural enhancement.
    
    This extractor identifies:
    - Agents (people, organizations)
    - Obligations (must, shall, required to)
    - Permissions (may, allowed to, can)
    - Prohibitions (forbidden, must not, prohibited)
    - Temporal constraints (within X days, always, eventually)
    - Conditionals (if...then)
    
    Example:
        >>> extractor = LogicAwareEntityExtractor()
        >>> entities = extractor.extract_entities("Alice must pay Bob within 30 days")
        >>> len(entities)
        4  # Alice (agent), Bob (agent), must pay (obligation), within 30 days (temporal)
    """
    
    def __init__(self, use_neural: bool = False):
        """Initialize the entity extractor.
        
        Args:
            use_neural: Whether to use neural enhancement (currently not implemented)
        """
        self.use_neural = use_neural
        self.neural_extractor = None
        
        if use_neural:
            # Try to import neural components
            try:
                from ipfs_datasets_py.logic.integration.neurosymbolic import EmbeddingProver
                self.neural_extractor = EmbeddingProver()
            except ImportError:
                self.use_neural = False
    
    def extract_entities(self, text: str) -> List[LogicalEntity]:
        """Extract all logical entities from text.
        
        Args:
            text: Input text to process
            
        Returns:
            List of extracted logical entities
        """
        entities = []
        
        # Pattern-based extraction
        entities.extend(self._extract_agents(text))
        entities.extend(self._extract_obligations(text))
        entities.extend(self._extract_permissions(text))
        entities.extend(self._extract_prohibitions(text))
        entities.extend(self._extract_temporal_constraints(text))
        entities.extend(self._extract_conditionals(text))
        
        # Neural enhancement if available
        if self.use_neural and self.neural_extractor:
            entities = self._enhance_with_neural(text, entities)
        
        return entities
    
    def _extract_agents(self, text: str) -> List[LogicalEntity]:
        """Extract agents (people, organizations) using proper noun detection.
        
        Args:
            text: Input text
            
        Returns:
            List of agent entities
        """
        agents = []
        
        # Look for capitalized words (proper nouns)
        pattern = r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b'
        for match in re.finditer(pattern, text):
            agent_text = match.group(1)
            # Filter out common words at sentence start
            if agent_text.lower() not in {'the', 'a', 'an', 'this', 'that', 'these', 'those'}:
                agents.append(LogicalEntity(
                    text=agent_text,
                    entity_type=LogicalEntityType.AGENT,
                    confidence=0.7,
                    metadata={'position': match.span()}
                ))
        
        return agents
    
    def _extract_obligations(self, text: str) -> List[LogicalEntity]:
        """Extract obligations (must, shall, required to).
        
        Args:
            text: Input text
            
        Returns:
            List of obligation entities
        """
        obligations = []
        
        # Obligation patterns with context
        patterns = [
            (r'(must\s+\w+(?:\s+\w+)*)', 0.85),
            (r'(shall\s+\w+(?:\s+\w+)*)', 0.85),
            (r'(required\s+to\s+\w+(?:\s+\w+)*)', 0.80),
            (r'(obligated\s+to\s+\w+(?:\s+\w+)*)', 0.80),
            (r'(has\s+to\s+\w+(?:\s+\w+)*)', 0.75)
        ]
        
        for pattern, confidence in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                obl_text = match.group(1)
                obligations.append(LogicalEntity(
                    text=obl_text,
                    entity_type=LogicalEntityType.OBLIGATION,
                    confidence=confidence,
                    metadata={'position': match.span()}
                ))
        
        return obligations
    
    def _extract_permissions(self, text: str) -> List[LogicalEntity]:
        """Extract permissions (may, allowed to, can).
        
        Args:
            text: Input text
            
        Returns:
            List of permission entities
        """
        permissions = []
        
        patterns = [
            (r'(may\s+\w+(?:\s+\w+)*)', 0.80),
            (r'(allowed\s+to\s+\w+(?:\s+\w+)*)', 0.85),
            (r'(can\s+\w+(?:\s+\w+)*)', 0.70),
            (r'(permitted\s+to\s+\w+(?:\s+\w+)*)', 0.85),
            (r'(has\s+permission\s+to\s+\w+(?:\s+\w+)*)', 0.85)
        ]
        
        for pattern, confidence in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                perm_text = match.group(1)
                permissions.append(LogicalEntity(
                    text=perm_text,
                    entity_type=LogicalEntityType.PERMISSION,
                    confidence=confidence,
                    metadata={'position': match.span()}
                ))
        
        return permissions
    
    def _extract_prohibitions(self, text: str) -> List[LogicalEntity]:
        """Extract prohibitions (forbidden, must not, prohibited).
        
        Args:
            text: Input text
            
        Returns:
            List of prohibition entities
        """
        prohibitions = []
        
        patterns = [
            (r'(forbidden\s+to\s+\w+(?:\s+\w+)*)', 0.90),
            (r'(must\s+not\s+\w+(?:\s+\w+)*)', 0.90),
            (r'(prohibited\s+from\s+\w+(?:\s+\w+)*)', 0.90),
            (r'(shall\s+not\s+\w+(?:\s+\w+)*)', 0.90),
            (r'(cannot\s+\w+(?:\s+\w+)*)', 0.75),
            (r'(may\s+not\s+\w+(?:\s+\w+)*)', 0.80)
        ]
        
        for pattern, confidence in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                proh_text = match.group(1)
                prohibitions.append(LogicalEntity(
                    text=proh_text,
                    entity_type=LogicalEntityType.PROHIBITION,
                    confidence=confidence,
                    metadata={'position': match.span()}
                ))
        
        return prohibitions
    
    def _extract_temporal_constraints(self, text: str) -> List[LogicalEntity]:
        """Extract temporal constraints (within X days, always, eventually).
        
        Args:
            text: Input text
            
        Returns:
            List of temporal constraint entities
        """
        constraints = []
        
        patterns = [
            (r'(within\s+\d+\s+\w+)', 0.85),
            (r'(after\s+\d+\s+\w+)', 0.85),
            (r'(before\s+\d+\s+\w+)', 0.85),
            (r'(in\s+\d+\s+\w+)', 0.80),
            (r'\b(always)\b', 0.90),
            (r'\b(eventually)\b', 0.85),
            (r'\b(never)\b', 0.90),
            (r'\b(immediately)\b', 0.85),
            (r'\b(soon)\b', 0.70)
        ]
        
        for pattern, confidence in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                temp_text = match.group(1)
                constraints.append(LogicalEntity(
                    text=temp_text,
                    entity_type=LogicalEntityType.TEMPORAL_CONSTRAINT,
                    confidence=confidence,
                    metadata={'position': match.span()}
                ))
        
        return constraints
    
    def _extract_conditionals(self, text: str) -> List[LogicalEntity]:
        """Extract conditional statements (if...then).
        
        Args:
            text: Input text
            
        Returns:
            List of conditional entities
        """
        conditionals = []
        
        # If-then patterns (simple version)
        patterns = [
            r'(if\s+.{10,100}?\s+then\s+.{10,100}?)(?:\.|,|;|$)',
            r'(when\s+.{10,100}?,\s+.{10,100}?)(?:\.|;|$)',
            r'(unless\s+.{10,100}?,\s+.{10,100}?)(?:\.|;|$)'
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE | re.DOTALL):
                cond_text = match.group(1).strip()
                # Limit to reasonable length
                if len(cond_text) < 200:
                    conditionals.append(LogicalEntity(
                        text=cond_text,
                        entity_type=LogicalEntityType.CONDITIONAL,
                        confidence=0.85,
                        metadata={'position': match.span()}
                    ))
        
        return conditionals
    
    def _enhance_with_neural(
        self, 
        text: str, 
        entities: List[LogicalEntity]
    ) -> List[LogicalEntity]:
        """Enhance entities using neural model (not yet implemented).
        
        Args:
            text: Original text
            entities: Extracted entities
            
        Returns:
            Enhanced entities
        """
        # TODO: Implement neural enhancement using EmbeddingProver
        # This would:
        # 1. Verify extracted entities
        # 2. Find additional entities using semantic similarity
        # 3. Improve confidence scores
        return entities
    
    def extract_relationships(
        self, 
        text: str, 
        entities: List[LogicalEntity]
    ) -> List[LogicalRelationship]:
        """Extract relationships between entities.
        
        Args:
            text: Original text
            entities: List of entities to find relationships between
            
        Returns:
            List of logical relationships
        """
        relationships = []
        
        # Simple relationship extraction based on proximity and patterns
        for i, entity1 in enumerate(entities):
            for entity2 in entities[i+1:]:
                # Check if entities are close in text
                pos1 = entity1.metadata.get('position', (0, 0))
                pos2 = entity2.metadata.get('position', (0, 0))
                
                distance = abs(pos1[0] - pos2[1])
                if distance < 50:  # Within 50 characters
                    # Infer relationship type based on entity types
                    rel_type = self._infer_relationship_type(entity1, entity2)
                    if rel_type:
                        relationships.append(LogicalRelationship(
                            source=entity1,
                            target=entity2,
                            relation_type=rel_type,
                            confidence=0.6
                        ))
        
        return relationships
    
    def _infer_relationship_type(
        self, 
        entity1: LogicalEntity, 
        entity2: LogicalEntity
    ) -> Optional[str]:
        """Infer relationship type between two entities.
        
        Args:
            entity1: First entity
            entity2: Second entity
            
        Returns:
            Relationship type or None
        """
        type1 = entity1.entity_type
        type2 = entity2.entity_type
        
        # Agent + Obligation = "must_do"
        if type1 == LogicalEntityType.AGENT and type2 == LogicalEntityType.OBLIGATION:
            return "must_do"
        
        # Agent + Permission = "may_do"
        if type1 == LogicalEntityType.AGENT and type2 == LogicalEntityType.PERMISSION:
            return "may_do"
        
        # Agent + Prohibition = "must_not_do"
        if type1 == LogicalEntityType.AGENT and type2 == LogicalEntityType.PROHIBITION:
            return "must_not_do"
        
        # Obligation/Permission/Prohibition + Temporal = "constrained_by"
        if type1 in {LogicalEntityType.OBLIGATION, LogicalEntityType.PERMISSION, 
                     LogicalEntityType.PROHIBITION} and type2 == LogicalEntityType.TEMPORAL_CONSTRAINT:
            return "constrained_by"
        
        # Agent + Agent = "interacts_with"
        if type1 == LogicalEntityType.AGENT and type2 == LogicalEntityType.AGENT:
            return "interacts_with"
        
        return None
