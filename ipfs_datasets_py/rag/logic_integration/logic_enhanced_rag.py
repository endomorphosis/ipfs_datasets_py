"""Logic-enhanced Retrieval-Augmented Generation.

This module provides the main LogicEnhancedRAG class that integrates
all logic components: entity extraction, knowledge graph construction,
theorem proving, and consistency checking.
"""

from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
import logging

from ipfs_datasets_py.rag.logic_integration.logic_aware_entity_extractor import (
    LogicAwareEntityExtractor,
    LogicalEntity
)
from ipfs_datasets_py.rag.logic_integration.logic_aware_knowledge_graph import (
    LogicAwareKnowledgeGraph,
    LogicNode
)
from ipfs_datasets_py.rag.logic_integration.theorem_augmented_rag import (
    TheoremAugmentedRAG
)

logger = logging.getLogger(__name__)


@dataclass
class RAGQueryResult:
    """Result of a logic-enhanced RAG query.
    
    Attributes:
        text: Original query text
        logical_entities: Entities extracted from query
        relevant_nodes: Relevant knowledge graph nodes
        related_theorems: Related theorems
        consistency_check: Whether knowledge graph is consistent
        reasoning_chain: Step-by-step reasoning process
        confidence: Overall confidence score
    """
    
    text: str
    logical_entities: List[LogicalEntity] = field(default_factory=list)
    relevant_nodes: List[LogicNode] = field(default_factory=list)
    related_theorems: List[tuple] = field(default_factory=list)
    consistency_check: bool = True
    reasoning_chain: List[str] = field(default_factory=list)
    confidence: float = 0.0


class LogicEnhancedRAG:
    """Complete logic-enhanced RAG system.
    
    This class provides a full RAG pipeline with:
    - Logic-aware entity extraction
    - Knowledge graph construction
    - Theorem integration
    - Consistency checking
    - Logical inference during retrieval
    
    Example:
        >>> rag = LogicEnhancedRAG()
        >>> rag.ingest_document("Alice must pay Bob within 30 days", "doc1")
        >>> result = rag.query("What are Alice's obligations?")
        >>> print(result.reasoning_chain)
    """
    
    def __init__(self, use_neural: bool = False):
        """Initialize logic-enhanced RAG system.
        
        Args:
            use_neural: Whether to use neural enhancement for entity extraction
        """
        self.kg = LogicAwareKnowledgeGraph()
        self.extractor = LogicAwareEntityExtractor(use_neural=use_neural)
        self.theorem_rag = TheoremAugmentedRAG(kg=self.kg)
        self.documents: Dict[str, str] = {}
        self.use_neural = use_neural
        
        # Try to initialize neural components
        self.reasoner = None
        if use_neural:
            self._init_neural_components()
    
    def _init_neural_components(self) -> None:
        """Initialize neural reasoning components if available."""
        try:
            from ipfs_datasets_py.logic.integration.neurosymbolic import ReasoningCoordinator
            self.reasoner = ReasoningCoordinator()
            logger.info("Neural reasoning coordinator initialized")
        except ImportError:
            logger.warning("Neural reasoning components not available")
    
    def ingest_document(self, text: str, doc_id: str) -> Dict[str, Any]:
        """Ingest a document into the knowledge graph.
        
        Args:
            text: Document text
            doc_id: Unique document identifier
            
        Returns:
            Dictionary with ingestion statistics
        """
        logger.info(f"Ingesting document: {doc_id}")
        
        # Store document
        self.documents[doc_id] = text
        
        # Extract entities
        entities = self.extractor.extract_entities(text)
        logger.info(f"Extracted {len(entities)} entities")
        
        # Extract relationships
        relationships = self.extractor.extract_relationships(text, entities)
        logger.info(f"Extracted {len(relationships)} relationships")
        
        # Add to knowledge graph
        node_ids = []
        for entity in entities:
            node_id = self.kg.add_node(entity)
            node_ids.append(node_id)
        
        for rel in relationships:
            self.kg.add_edge(rel)
        
        # Check consistency
        is_consistent, inconsistencies = self.kg.check_consistency()
        if not is_consistent:
            logger.warning(f"Inconsistencies found in {doc_id}:")
            for inc in inconsistencies:
                logger.warning(f"  - {inc}")
        
        return {
            'doc_id': doc_id,
            'entities_extracted': len(entities),
            'relationships_extracted': len(relationships),
            'nodes_created': len(node_ids),
            'is_consistent': is_consistent,
            'inconsistencies': inconsistencies
        }
    
    def query(
        self, 
        query_text: str, 
        use_inference: bool = True,
        top_k: int = 10
    ) -> RAGQueryResult:
        """Query the knowledge graph with logical reasoning.
        
        Args:
            query_text: Query text
            use_inference: Whether to use logical inference
            top_k: Maximum number of results to return
            
        Returns:
            Logic-enhanced query result
        """
        logger.info(f"Processing query: {query_text}")
        
        reasoning_chain = []
        
        # Extract entities from query
        query_entities = self.extractor.extract_entities(query_text)
        reasoning_chain.append(f"Extracted {len(query_entities)} entities from query")
        
        # Find relevant nodes in knowledge graph
        relevant_nodes = self.kg.query(query_text, top_k=top_k)
        reasoning_chain.append(f"Found {len(relevant_nodes)} relevant nodes in knowledge graph")
        
        # Get related theorems if inference is enabled
        related_theorems = []
        if use_inference:
            for node in relevant_nodes:
                theorems = self.kg.get_related_theorems(node.id)
                related_theorems.extend(theorems)
            
            # Remove duplicates
            related_theorems = list(set(related_theorems))
            reasoning_chain.append(f"Retrieved {len(related_theorems)} related theorems")
        
        # Check consistency
        is_consistent, inconsistencies = self.kg.check_consistency()
        reasoning_chain.append(
            f"Knowledge graph is {'consistent' if is_consistent else 'inconsistent'}"
        )
        
        if inconsistencies:
            reasoning_chain.append(f"Found {len(inconsistencies)} inconsistencies")
        
        # Calculate confidence score
        confidence = self._calculate_confidence(
            query_entities, 
            relevant_nodes, 
            related_theorems,
            is_consistent
        )
        reasoning_chain.append(f"Overall confidence: {confidence:.2f}")
        
        return RAGQueryResult(
            text=query_text,
            logical_entities=query_entities,
            relevant_nodes=relevant_nodes,
            related_theorems=related_theorems,
            consistency_check=is_consistent,
            reasoning_chain=reasoning_chain,
            confidence=confidence
        )
    
    def _calculate_confidence(
        self,
        query_entities: List[LogicalEntity],
        relevant_nodes: List[LogicNode],
        related_theorems: List[tuple],
        is_consistent: bool
    ) -> float:
        """Calculate overall confidence score for a query result.
        
        Args:
            query_entities: Entities from query
            relevant_nodes: Relevant graph nodes
            related_theorems: Related theorems
            is_consistent: Whether graph is consistent
            
        Returns:
            Confidence score (0-1)
        """
        # Base confidence from entity extraction
        entity_confidence = (
            sum(e.confidence for e in query_entities) / len(query_entities)
            if query_entities else 0.5
        )
        
        # Boost for having relevant nodes
        relevance_boost = min(len(relevant_nodes) / 10, 0.3)
        
        # Boost for having related theorems
        theorem_boost = min(len(related_theorems) / 5, 0.1)
        
        # Penalty for inconsistency
        consistency_penalty = 0 if is_consistent else 0.2
        
        confidence = entity_confidence + relevance_boost + theorem_boost - consistency_penalty
        return max(0.0, min(1.0, confidence))
    
    def add_theorem(self, name: str, formula: Any, auto_prove: bool = False) -> bool:
        """Add a theorem to the knowledge graph.
        
        Args:
            name: Theorem name
            formula: Theorem formula
            auto_prove: Whether to automatically prove the theorem
            
        Returns:
            True if theorem was proven/added successfully
        """
        return self.theorem_rag.add_theorem(name, formula, auto_prove=auto_prove)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive statistics about the RAG system.
        
        Returns:
            Dictionary with various statistics
        """
        kg_stats = self.kg.get_stats()
        theorem_stats = self.theorem_rag.get_theorem_stats()
        
        return {
            'documents_ingested': len(self.documents),
            **kg_stats,
            **theorem_stats,
            'using_neural': self.use_neural,
            'reasoner_available': self.reasoner is not None
        }
    
    def export_knowledge_graph(self) -> Dict[str, Any]:
        """Export the knowledge graph to dictionary format.
        
        Returns:
            Dictionary representation of the knowledge graph
        """
        return self.kg.export_to_dict()
    
    def check_consistency(self) -> tuple:
        """Check knowledge graph consistency.
        
        Returns:
            Tuple of (is_consistent, list of inconsistencies)
        """
        return self.kg.check_consistency()
