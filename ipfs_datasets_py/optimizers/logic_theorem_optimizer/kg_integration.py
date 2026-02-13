"""Knowledge Graph Integration for Logic Theorem Optimizer.

This module provides integration with LogicAwareKnowledgeGraph and related
components for enhanced context-aware logic extraction and ontology management.

Integrates:
- LogicAwareKnowledgeGraph for storing logical statements
- LogicAwareEntityExtractor for entity extraction
- TheoremAugmentedRAG for theorem storage
- Ontology loading and management
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class KnowledgeGraphContext:
    """Context from knowledge graph for extraction.
    
    Attributes:
        entities: Extracted entities
        relationships: Extracted relationships  
        ontology: Ontology constraints
        relevant_theorems: Related theorems
        metadata: Additional metadata
    """
    entities: List[Any] = None
    relationships: List[Any] = None
    ontology: Dict[str, Any] = None
    relevant_theorems: List[Any] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.entities is None:
            self.entities = []
        if self.relationships is None:
            self.relationships = []
        if self.ontology is None:
            self.ontology = {}
        if self.relevant_theorems is None:
            self.relevant_theorems = []
        if self.metadata is None:
            self.metadata = {}


class KnowledgeGraphIntegration:
    """Integration with knowledge graph systems.
    
    This adapter provides:
    - Knowledge graph loading and querying
    - Entity extraction from text
    - Theorem storage and retrieval
    - Ontology constraint extraction
    - Context enrichment for extraction
    
    Example:
        >>> kg_integration = KnowledgeGraphIntegration()
        >>> context = kg_integration.get_context_for_extraction("legal contract text")
        >>> print(f"Found {len(context.entities)} entities")
    """
    
    def __init__(
        self,
        kg: Optional[Any] = None,
        enable_entity_extraction: bool = True,
        enable_theorem_augmentation: bool = True
    ):
        """Initialize knowledge graph integration.
        
        Args:
            kg: Optional existing LogicAwareKnowledgeGraph
            enable_entity_extraction: Enable entity extraction
            enable_theorem_augmentation: Enable theorem augmentation
        """
        self.enable_entity_extraction = enable_entity_extraction
        self.enable_theorem_augmentation = enable_theorem_augmentation
        
        # Initialize components
        self.kg = kg
        self.entity_extractor = None
        self.theorem_rag = None
        
        self._init_components()
        
        # Statistics
        self.stats = {
            'entities_extracted': 0,
            'theorems_added': 0,
            'queries': 0
        }
    
    def _init_components(self) -> None:
        """Initialize knowledge graph components."""
        # Initialize knowledge graph
        if self.kg is None:
            try:
                from ipfs_datasets_py.rag.logic_integration.logic_aware_knowledge_graph import LogicAwareKnowledgeGraph
                self.kg = LogicAwareKnowledgeGraph()
                logger.info("Initialized LogicAwareKnowledgeGraph")
            except ImportError as e:
                logger.warning(f"Could not initialize knowledge graph: {e}")
                self.kg = None
        
        # Initialize entity extractor
        if self.enable_entity_extraction:
            try:
                from ipfs_datasets_py.rag.logic_integration.logic_aware_entity_extractor import LogicAwareEntityExtractor
                self.entity_extractor = LogicAwareEntityExtractor()
                logger.info("Initialized LogicAwareEntityExtractor")
            except ImportError as e:
                logger.warning(f"Could not initialize entity extractor: {e}")
                self.entity_extractor = None
        
        # Initialize theorem RAG
        if self.enable_theorem_augmentation and self.kg:
            try:
                from ipfs_datasets_py.rag.logic_integration.theorem_augmented_rag import TheoremAugmentedRAG
                self.theorem_rag = TheoremAugmentedRAG(kg=self.kg)
                logger.info("Initialized TheoremAugmentedRAG")
            except ImportError as e:
                logger.warning(f"Could not initialize theorem RAG: {e}")
                self.theorem_rag = None
    
    def get_context_for_extraction(
        self,
        text: str,
        extract_entities: bool = True
    ) -> KnowledgeGraphContext:
        """Get knowledge graph context for extraction.
        
        Args:
            text: Input text to extract context from
            extract_entities: Whether to extract entities
            
        Returns:
            KnowledgeGraphContext with extracted information
        """
        self.stats['queries'] += 1
        
        context = KnowledgeGraphContext()
        
        # Extract entities from text
        if extract_entities and self.entity_extractor:
            try:
                entities = self.entity_extractor.extract_entities(text)
                relationships = self.entity_extractor.extract_relationships(text)
                context.entities = entities
                context.relationships = relationships
                self.stats['entities_extracted'] += len(entities)
                logger.debug(f"Extracted {len(entities)} entities, {len(relationships)} relationships")
            except Exception as e:
                logger.warning(f"Entity extraction error: {e}")
        
        # Get ontology constraints
        if self.kg:
            try:
                context.ontology = self._extract_ontology_constraints()
            except Exception as e:
                logger.warning(f"Ontology extraction error: {e}")
        
        # Get relevant theorems
        if self.theorem_rag:
            try:
                context.relevant_theorems = self._get_relevant_theorems(text)
            except Exception as e:
                logger.warning(f"Theorem retrieval error: {e}")
        
        return context
    
    def add_statement_to_kg(
        self,
        statement: Any,
        proven: bool = False
    ) -> bool:
        """Add a logical statement to the knowledge graph.
        
        Args:
            statement: Logical statement to add
            proven: Whether statement is proven
            
        Returns:
            True if added successfully
        """
        if not self.kg:
            logger.warning("Knowledge graph not available")
            return False
        
        try:
            # Extract formula and text
            formula = getattr(statement, 'formula', str(statement))
            text = getattr(statement, 'natural_language', str(statement))
            
            # Create entity
            from ipfs_datasets_py.rag.logic_integration.logic_aware_entity_extractor import (
                LogicalEntity, LogicalEntityType
            )
            entity = LogicalEntity(
                text=text,
                entity_type=LogicalEntityType.PREDICATE,
                confidence=getattr(statement, 'confidence', 0.7),
                formula=formula
            )
            
            # Add to knowledge graph
            node_id = self.kg.add_node(entity)
            
            # If proven, add as theorem
            if proven and self.theorem_rag:
                self.theorem_rag.add_theorem(
                    name=f"stmt_{node_id}",
                    formula=formula,
                    auto_prove=False  # Already proven
                )
                self.stats['theorems_added'] += 1
            
            return True
            
        except Exception as e:
            logger.error(f"Error adding statement to KG: {e}")
            return False
    
    def load_ontology(
        self,
        ontology_dict: Dict[str, Any]
    ) -> bool:
        """Load ontology into knowledge graph.
        
        Args:
            ontology_dict: Ontology dictionary
            
        Returns:
            True if loaded successfully
        """
        if not self.kg:
            logger.warning("Knowledge graph not available")
            return False
        
        try:
            # Load entity types
            if 'entity_types' in ontology_dict:
                for entity_type, properties in ontology_dict['entity_types'].items():
                    logger.debug(f"Loaded entity type: {entity_type}")
            
            # Load relationship types
            if 'relationship_types' in ontology_dict:
                for rel_type, properties in ontology_dict['relationship_types'].items():
                    logger.debug(f"Loaded relationship type: {rel_type}")
            
            # Store ontology in metadata
            if hasattr(self.kg, 'metadata'):
                self.kg.metadata['ontology'] = ontology_dict
            
            logger.info(f"Loaded ontology with {len(ontology_dict.get('entity_types', {}))} entity types")
            return True
            
        except Exception as e:
            logger.error(f"Error loading ontology: {e}")
            return False
    
    def query_kg(
        self,
        query: str,
        top_k: int = 10
    ) -> List[Any]:
        """Query the knowledge graph.
        
        Args:
            query: Query text
            top_k: Number of top results
            
        Returns:
            List of relevant nodes
        """
        if not self.kg:
            return []
        
        try:
            results = self.kg.query(query, limit=top_k)
            return results
        except Exception as e:
            logger.warning(f"KG query error: {e}")
            return []
    
    def _extract_ontology_constraints(self) -> Dict[str, Any]:
        """Extract ontology constraints from knowledge graph.
        
        Returns:
            Dictionary of ontology constraints
        """
        constraints = {
            'entity_types': set(),
            'relationship_types': set(),
            'patterns': []
        }
        
        # Extract from existing nodes
        if hasattr(self.kg, 'nodes'):
            for node in self.kg.nodes.values():
                if hasattr(node, 'entity') and hasattr(node.entity, 'entity_type'):
                    constraints['entity_types'].add(node.entity.entity_type.value)
        
        # Extract from existing edges
        if hasattr(self.kg, 'edges'):
            for edge in self.kg.edges:
                if hasattr(edge, 'relationship') and hasattr(edge.relationship, 'relation_type'):
                    constraints['relationship_types'].add(edge.relationship.relation_type)
        
        # Convert sets to lists for JSON serialization
        constraints['entity_types'] = list(constraints['entity_types'])
        constraints['relationship_types'] = list(constraints['relationship_types'])
        
        return constraints
    
    def _get_relevant_theorems(
        self,
        text: str,
        top_k: int = 5
    ) -> List[Any]:
        """Get theorems relevant to the text.
        
        Args:
            text: Input text
            top_k: Number of theorems to retrieve
            
        Returns:
            List of relevant theorems
        """
        if not self.theorem_rag:
            return []
        
        try:
            # Query with theorems
            results = self.theorem_rag.query_with_theorems(text, use_inference=False)
            
            # Filter for theorems only
            theorems = [r for r in results if getattr(r, 'proven', False)]
            
            return theorems[:top_k]
            
        except Exception as e:
            logger.warning(f"Theorem retrieval error: {e}")
            return []
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get integration statistics.
        
        Returns:
            Statistics dictionary
        """
        stats = self.stats.copy()
        
        # Add component availability
        stats['kg_available'] = self.kg is not None
        stats['entity_extractor_available'] = self.entity_extractor is not None
        stats['theorem_rag_available'] = self.theorem_rag is not None
        
        # Add KG stats if available
        if self.kg:
            if hasattr(self.kg, 'nodes'):
                stats['kg_nodes'] = len(self.kg.nodes)
            if hasattr(self.kg, 'edges'):
                stats['kg_edges'] = len(self.kg.edges)
            if hasattr(self.kg, 'theorems'):
                stats['kg_theorems'] = len(self.kg.theorems)
        
        return stats


def get_default_kg_integration() -> KnowledgeGraphIntegration:
    """Get default knowledge graph integration.
    
    Returns:
        Configured KnowledgeGraphIntegration
    """
    return KnowledgeGraphIntegration(
        enable_entity_extraction=True,
        enable_theorem_augmentation=True
    )
