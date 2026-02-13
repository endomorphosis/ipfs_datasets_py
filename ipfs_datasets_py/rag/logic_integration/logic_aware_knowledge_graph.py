"""Logic-aware knowledge graph for GraphRAG.

This module provides a knowledge graph implementation that integrates
logical reasoning capabilities, including consistency checking and
theorem augmentation.
"""

from typing import List, Dict, Set, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime
import logging

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False

from ipfs_datasets_py.rag.logic_integration.logic_aware_entity_extractor import (
    LogicalEntity,
    LogicalRelationship,
    LogicalEntityType
)

logger = logging.getLogger(__name__)


@dataclass
class LogicNode:
    """A node in the logic knowledge graph.
    
    Attributes:
        id: Unique node identifier
        entity: The logical entity this node represents
        formula: Optional TDFOL formula
        proven: Whether this node represents a proven theorem
        metadata: Additional metadata
        created_at: Creation timestamp
    """
    
    id: str
    entity: LogicalEntity
    formula: Optional[Any] = None
    proven: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class LogicEdge:
    """An edge in the logic knowledge graph.
    
    Attributes:
        source_id: Source node ID
        target_id: Target node ID
        relationship: The logical relationship
        confidence: Confidence score (0-1)
        metadata: Additional metadata
    """
    
    source_id: str
    target_id: str
    relationship: LogicalRelationship
    confidence: float
    metadata: Dict[str, Any] = field(default_factory=dict)


class LogicAwareKnowledgeGraph:
    """Knowledge graph with integrated logical reasoning capabilities.
    
    This class provides:
    - Logic-aware node and edge management
    - Theorem storage and retrieval
    - Consistency checking for logical contradictions
    - Query capabilities with logical inference
    
    Example:
        >>> kg = LogicAwareKnowledgeGraph()
        >>> entity = LogicalEntity("Alice", LogicalEntityType.AGENT, 0.9)
        >>> node_id = kg.add_node(entity)
        >>> is_consistent, issues = kg.check_consistency()
    """
    
    def __init__(self):
        """Initialize the logic knowledge graph."""
        if HAS_NETWORKX:
            self.graph = nx.DiGraph()
        else:
            self.graph = None
            logger.warning("NetworkX not available, graph operations will be limited")
        
        self.nodes: Dict[str, LogicNode] = {}
        self.edges: List[LogicEdge] = []
        self.theorems: Dict[str, Any] = {}
        self._node_counter = 0
    
    def add_node(self, entity: LogicalEntity) -> str:
        """Add a node to the graph.
        
        Args:
            entity: Logical entity to add
            
        Returns:
            Unique node ID
        """
        node_id = f"{entity.entity_type.value}_{self._node_counter}"
        self._node_counter += 1
        
        node = LogicNode(id=node_id, entity=entity, formula=entity.formula)
        self.nodes[node_id] = node
        
        if self.graph is not None:
            self.graph.add_node(node_id, **{
                'text': entity.text,
                'type': entity.entity_type.value,
                'confidence': entity.confidence
            })
        
        return node_id
    
    def add_edge(self, relationship: LogicalRelationship) -> None:
        """Add an edge to the graph.
        
        Args:
            relationship: Logical relationship to add
        """
        # Find or create nodes
        source_id = self._find_or_create_node(relationship.source)
        target_id = self._find_or_create_node(relationship.target)
        
        # Create edge
        edge = LogicEdge(
            source_id=source_id,
            target_id=target_id,
            relationship=relationship,
            confidence=relationship.confidence
        )
        
        self.edges.append(edge)
        
        if self.graph is not None:
            self.graph.add_edge(
                source_id,
                target_id,
                relation=relationship.relation_type,
                confidence=relationship.confidence
            )
    
    def _find_or_create_node(self, entity: LogicalEntity) -> str:
        """Find existing node or create new one.
        
        Args:
            entity: Entity to find or create
            
        Returns:
            Node ID
        """
        # Try to find existing node with same text and type
        for node_id, node in self.nodes.items():
            if (node.entity.text == entity.text and 
                node.entity.entity_type == entity.entity_type):
                return node_id
        
        # Create new node
        return self.add_node(entity)
    
    def add_theorem(self, name: str, formula: Any, proven: bool = True) -> None:
        """Add a proven theorem to the graph.
        
        Args:
            name: Theorem name
            formula: Theorem formula
            proven: Whether the theorem is proven
        """
        self.theorems[name] = formula
        
        # Add as special node in graph
        if self.graph is not None:
            node_id = f"theorem_{name}"
            self.graph.add_node(node_id, **{
                'text': str(formula),
                'type': 'theorem',
                'proven': proven,
                'name': name
            })
    
    def check_consistency(self) -> Tuple[bool, List[str]]:
        """Check knowledge graph for logical inconsistencies.
        
        Returns:
            Tuple of (is_consistent, list of inconsistency descriptions)
        """
        inconsistencies = []
        
        # Check for contradicting obligations
        obligations = [
            node for node in self.nodes.values()
            if node.entity.entity_type == LogicalEntityType.OBLIGATION
        ]
        
        for i, obl1 in enumerate(obligations):
            for obl2 in obligations[i+1:]:
                if self._are_contradictory(obl1, obl2):
                    inconsistencies.append(
                        f"Contradictory obligations: '{obl1.entity.text}' vs '{obl2.entity.text}'"
                    )
        
        # Check obligations vs prohibitions
        prohibitions = [
            node for node in self.nodes.values()
            if node.entity.entity_type == LogicalEntityType.PROHIBITION
        ]
        
        for obl in obligations:
            for proh in prohibitions:
                # Don't compare same node with itself
                if obl.id != proh.id and self._conflict(obl, proh):
                    inconsistencies.append(
                        f"Obligation conflicts with prohibition: '{obl.entity.text}' vs '{proh.entity.text}'"
                    )
        
        # Check for temporal contradictions
        temporal_issues = self._check_temporal_consistency()
        inconsistencies.extend(temporal_issues)
        
        is_consistent = len(inconsistencies) == 0
        return is_consistent, inconsistencies
    
    def _are_contradictory(self, node1: LogicNode, node2: LogicNode) -> bool:
        """Check if two nodes are contradictory.
        
        Args:
            node1: First node
            node2: Second node
            
        Returns:
            True if nodes are contradictory
        """
        text1 = node1.entity.text.lower()
        text2 = node2.entity.text.lower()
        
        # Remove modal words to get core actions
        for word in ['must', 'shall', 'has to', 'required to']:
            text1 = text1.replace(word, '').strip()
            text2 = text2.replace(word, '').strip()
        
        # Check for negation patterns
        if "not" in text1:
            text1_without_not = text1.replace("not", "").strip()
            if text1_without_not == text2 or text1_without_not in text2 or text2 in text1_without_not:
                return True
        
        if "not" in text2:
            text2_without_not = text2.replace("not", "").strip()
            if text2_without_not == text1 or text2_without_not in text1 or text1 in text2_without_not:
                return True
        
        return False
    
    def _conflict(self, obl: LogicNode, proh: LogicNode) -> bool:
        """Check if obligation conflicts with prohibition.
        
        Args:
            obl: Obligation node
            proh: Prohibition node
            
        Returns:
            True if there's a conflict
        """
        obl_text = obl.entity.text.lower()
        proh_text = proh.entity.text.lower()
        
        # Remove modal words to extract action
        for word in ['must', 'shall', 'has to', 'required to']:
            obl_text = obl_text.replace(word, '')
        
        for word in ['forbidden to', 'must not', 'shall not', 'prohibited from', 'may not']:
            proh_text = proh_text.replace(word, '')
        
        obl_text = obl_text.strip()
        proh_text = proh_text.strip()
        
        # Check if same action
        return obl_text == proh_text or obl_text in proh_text or proh_text in obl_text
    
    def _check_temporal_consistency(self) -> List[str]:
        """Check for temporal inconsistencies.
        
        Returns:
            List of temporal inconsistency descriptions
        """
        issues = []
        
        # Find nodes with temporal constraints
        temporal_nodes = [
            node for node in self.nodes.values()
            if node.entity.entity_type == LogicalEntityType.TEMPORAL_CONSTRAINT
        ]
        
        # Check for "always" vs "never" conflicts
        always_nodes = [n for n in temporal_nodes if 'always' in n.entity.text.lower()]
        never_nodes = [n for n in temporal_nodes if 'never' in n.entity.text.lower()]
        
        if always_nodes and never_nodes:
            issues.append(
                f"Temporal conflict: 'always' constraint conflicts with 'never' constraint"
            )
        
        return issues
    
    def query(self, query_text: str, top_k: int = 10) -> List[LogicNode]:
        """Query the knowledge graph using keyword matching.
        
        Args:
            query_text: Query text
            top_k: Maximum number of results to return
            
        Returns:
            List of relevant nodes
        """
        results = []
        query_lower = query_text.lower()
        
        # Score nodes by keyword overlap
        scored_nodes = []
        query_words = set(query_lower.split())
        
        for node in self.nodes.values():
            node_words = set(node.entity.text.lower().split())
            overlap = len(query_words & node_words)
            
            if overlap > 0 or query_lower in node.entity.text.lower():
                score = overlap + (2 if query_lower in node.entity.text.lower() else 0)
                scored_nodes.append((score, node))
        
        # Sort by score and return top_k
        scored_nodes.sort(key=lambda x: x[0], reverse=True)
        results = [node for _, node in scored_nodes[:top_k]]
        
        return results
    
    def get_related_theorems(self, node_id: str) -> List[Tuple[str, Any]]:
        """Get theorems related to a node.
        
        Args:
            node_id: Node ID to find theorems for
            
        Returns:
            List of (theorem_name, formula) tuples
        """
        related = []
        
        if node_id not in self.nodes:
            return related
        
        node = self.nodes[node_id]
        node_text_lower = node.entity.text.lower()
        
        # Find theorems with similar keywords
        for name, formula in self.theorems.items():
            formula_str = str(formula).lower()
            # Simple keyword matching
            if any(word in formula_str for word in node_text_lower.split()):
                related.append((name, formula))
        
        return related
    
    def export_to_dict(self) -> Dict[str, Any]:
        """Export graph to dictionary format.
        
        Returns:
            Dictionary with nodes, edges, and theorems
        """
        return {
            'nodes': [
                {
                    'id': node_id,
                    'text': node.entity.text,
                    'type': node.entity.entity_type.value,
                    'confidence': node.entity.confidence,
                    'proven': node.proven
                }
                for node_id, node in self.nodes.items()
            ],
            'edges': [
                {
                    'source': edge.source_id,
                    'target': edge.target_id,
                    'relation': edge.relationship.relation_type,
                    'confidence': edge.confidence
                }
                for edge in self.edges
            ],
            'theorems': {
                name: str(formula)
                for name, formula in self.theorems.items()
            }
        }
    
    def get_stats(self) -> Dict[str, int]:
        """Get graph statistics.
        
        Returns:
            Dictionary with node, edge, and theorem counts
        """
        return {
            'nodes': len(self.nodes),
            'edges': len(self.edges),
            'theorems': len(self.theorems),
            'agents': len([n for n in self.nodes.values() 
                          if n.entity.entity_type == LogicalEntityType.AGENT]),
            'obligations': len([n for n in self.nodes.values() 
                               if n.entity.entity_type == LogicalEntityType.OBLIGATION]),
            'permissions': len([n for n in self.nodes.values() 
                               if n.entity.entity_type == LogicalEntityType.PERMISSION]),
            'prohibitions': len([n for n in self.nodes.values() 
                                if n.entity.entity_type == LogicalEntityType.PROHIBITION]),
        }
