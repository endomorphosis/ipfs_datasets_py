# GraphRAG Integration: Detailed Implementation Plan

**Date:** 2026-02-12  
**Phase:** 5 of Production Readiness Plan  
**Timeline:** 2 weeks (Week 7-8)  
**Status:** Implementation Ready

---

## Executive Summary

This document provides detailed implementation guidelines for integrating logical reasoning capabilities with the existing GraphRAG system, creating a true neurosymbolic knowledge graph architecture.

### Goals
1. **Logic-Aware Entity Extraction** - Automatically identify logical entities and relationships
2. **Theorem-Augmented Knowledge Graph** - Store proven theorems alongside factual knowledge
3. **Consistency Checking** - Validate knowledge graph for logical contradictions
4. **Semantic Query Enhancement** - Use logic to improve query understanding and results

---

## Week 7: Foundation & Entity Extraction

### Day 1-2: Logic-Aware Entity Extractor

#### File: `ipfs_datasets_py/rag/logic_aware_entity_extractor.py`

```python
"""Logic-aware entity extraction for GraphRAG."""

from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from enum import Enum

from ipfs_datasets_py.logic.TDFOL import (
    parse_tdfol, 
    Formula,
    Predicate,
    DeonticFormula,
    TemporalFormula
)

class LogicalEntityType(Enum):
    """Types of logical entities."""
    AGENT = "agent"  # e.g., "Alice", "Bob", "Company A"
    PREDICATE = "predicate"  # e.g., "owns", "pays", "delivers"
    OBLIGATION = "obligation"  # e.g., "must pay", "shall deliver"
    PERMISSION = "permission"  # e.g., "may access", "can modify"
    PROHIBITION = "prohibition"  # e.g., "forbidden to", "must not"
    TEMPORAL_CONSTRAINT = "temporal"  # e.g., "within 30 days", "always"
    CONDITIONAL = "conditional"  # e.g., "if... then..."

@dataclass
class LogicalEntity:
    """A logical entity extracted from text."""
    text: str
    entity_type: LogicalEntityType
    confidence: float
    formula: Optional[Formula] = None
    metadata: Dict = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

@dataclass
class LogicalRelationship:
    """A logical relationship between entities."""
    source: LogicalEntity
    target: LogicalEntity
    relation_type: str
    confidence: float
    formula: Optional[Formula] = None

class LogicAwareEntityExtractor:
    """Extract logical entities from text."""
    
    def __init__(self, use_neural: bool = True):
        """Initialize extractor.
        
        Args:
            use_neural: Whether to use SymbolicAI for entity recognition
        """
        self.use_neural = use_neural
        if use_neural:
            try:
                from ipfs_datasets_py.logic.external_provers import (
                    SymbolicAIProverBridge
                )
                self.neural_extractor = SymbolicAIProverBridge()
            except ImportError:
                self.neural_extractor = None
                self.use_neural = False
    
    def extract_entities(self, text: str) -> List[LogicalEntity]:
        """Extract logical entities from text.
        
        Args:
            text: Input text
            
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
        """Extract agents (people, organizations)."""
        import re
        agents = []
        
        # Look for capitalized words (proper nouns)
        pattern = r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b'
        for match in re.finditer(pattern, text):
            agent_text = match.group(1)
            agents.append(LogicalEntity(
                text=agent_text,
                entity_type=LogicalEntityType.AGENT,
                confidence=0.7,
                metadata={'position': match.span()}
            ))
        
        return agents
    
    def _extract_obligations(self, text: str) -> List[LogicalEntity]:
        """Extract obligations (must, shall, required to)."""
        import re
        obligations = []
        
        # Obligation patterns
        patterns = [
            r'(must\s+\w+)',
            r'(shall\s+\w+)',
            r'(required\s+to\s+\w+)',
            r'(obligated\s+to\s+\w+)'
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                obl_text = match.group(1)
                
                # Try to convert to TDFOL formula
                try:
                    formula = parse_tdfol(f"O({obl_text})")
                except:
                    formula = None
                
                obligations.append(LogicalEntity(
                    text=obl_text,
                    entity_type=LogicalEntityType.OBLIGATION,
                    confidence=0.8,
                    formula=formula,
                    metadata={'position': match.span()}
                ))
        
        return obligations
    
    def _extract_permissions(self, text: str) -> List[LogicalEntity]:
        """Extract permissions (may, allowed to, can)."""
        import re
        permissions = []
        
        patterns = [
            r'(may\s+\w+)',
            r'(allowed\s+to\s+\w+)',
            r'(can\s+\w+)',
            r'(permitted\s+to\s+\w+)'
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                perm_text = match.group(1)
                
                try:
                    formula = parse_tdfol(f"P({perm_text})")
                except:
                    formula = None
                
                permissions.append(LogicalEntity(
                    text=perm_text,
                    entity_type=LogicalEntityType.PERMISSION,
                    confidence=0.7,
                    formula=formula,
                    metadata={'position': match.span()}
                ))
        
        return permissions
    
    def _extract_prohibitions(self, text: str) -> List[LogicalEntity]:
        """Extract prohibitions (forbidden, must not, prohibited)."""
        import re
        prohibitions = []
        
        patterns = [
            r'(forbidden\s+to\s+\w+)',
            r'(must\s+not\s+\w+)',
            r'(prohibited\s+from\s+\w+)',
            r'(shall\s+not\s+\w+)'
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                proh_text = match.group(1)
                
                try:
                    formula = parse_tdfol(f"F({proh_text})")
                except:
                    formula = None
                
                prohibitions.append(LogicalEntity(
                    text=proh_text,
                    entity_type=LogicalEntityType.PROHIBITION,
                    confidence=0.8,
                    formula=formula,
                    metadata={'position': match.span()}
                ))
        
        return prohibitions
    
    def _extract_temporal_constraints(self, text: str) -> List[LogicalEntity]:
        """Extract temporal constraints (within X days, always, eventually)."""
        import re
        constraints = []
        
        patterns = [
            r'(within\s+\d+\s+\w+)',
            r'(after\s+\d+\s+\w+)',
            r'(before\s+\d+\s+\w+)',
            r'(always)',
            r'(eventually)',
            r'(never)'
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                temp_text = match.group(1)
                constraints.append(LogicalEntity(
                    text=temp_text,
                    entity_type=LogicalEntityType.TEMPORAL_CONSTRAINT,
                    confidence=0.75,
                    metadata={'position': match.span()}
                ))
        
        return constraints
    
    def _extract_conditionals(self, text: str) -> List[LogicalEntity]:
        """Extract conditional statements (if...then)."""
        import re
        conditionals = []
        
        # If-then patterns
        pattern = r'(if\s+.*?\s+then\s+.*?)(?:\.|$)'
        for match in re.finditer(pattern, text, re.IGNORECASE):
            cond_text = match.group(1)
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
        """Enhance entities using neural model."""
        # Use SymbolicAI to improve extraction
        # This would use LLM to:
        # 1. Verify extracted entities
        # 2. Find additional entities
        # 3. Improve confidence scores
        
        # For now, just return original entities
        # TODO: Implement neural enhancement
        return entities
    
    def extract_relationships(
        self, 
        text: str, 
        entities: List[LogicalEntity]
    ) -> List[LogicalRelationship]:
        """Extract relationships between entities.
        
        Args:
            text: Source text
            entities: Extracted entities
            
        Returns:
            List of logical relationships
        """
        relationships = []
        
        # Find relationships based on proximity and patterns
        for i, entity1 in enumerate(entities):
            for entity2 in entities[i+1:]:
                rel = self._find_relationship(text, entity1, entity2)
                if rel:
                    relationships.append(rel)
        
        return relationships
    
    def _find_relationship(
        self,
        text: str,
        entity1: LogicalEntity,
        entity2: LogicalEntity
    ) -> Optional[LogicalRelationship]:
        """Find relationship between two entities."""
        # Check if entities are close in text
        pos1 = entity1.metadata.get('position', (0, 0))
        pos2 = entity2.metadata.get('position', (0, 0))
        
        # If within 50 characters, there's likely a relationship
        if abs(pos1[1] - pos2[0]) < 50:
            # Determine relationship type
            if entity1.entity_type == LogicalEntityType.AGENT:
                if entity2.entity_type == LogicalEntityType.OBLIGATION:
                    return LogicalRelationship(
                        source=entity1,
                        target=entity2,
                        relation_type="has_obligation",
                        confidence=0.8
                    )
                elif entity2.entity_type == LogicalEntityType.PERMISSION:
                    return LogicalRelationship(
                        source=entity1,
                        target=entity2,
                        relation_type="has_permission",
                        confidence=0.75
                    )
        
        return None
```

### Day 3-4: Knowledge Graph Integration

#### File: `ipfs_datasets_py/rag/logic_knowledge_graph.py`

```python
"""Logic-aware knowledge graph for GraphRAG."""

from typing import List, Dict, Set, Optional, Tuple
from dataclasses import dataclass, field
import networkx as nx
from datetime import datetime

from ipfs_datasets_py.logic.TDFOL import Formula, parse_tdfol
from ipfs_datasets_py.rag.logic_aware_entity_extractor import (
    LogicalEntity,
    LogicalRelationship,
    LogicalEntityType
)

@dataclass
class LogicNode:
    """A node in the logic knowledge graph."""
    id: str
    entity: LogicalEntity
    formula: Optional[Formula] = None
    proven: bool = False
    metadata: Dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)

@dataclass
class LogicEdge:
    """An edge in the logic knowledge graph."""
    source_id: str
    target_id: str
    relationship: LogicalRelationship
    confidence: float
    metadata: Dict = field(default_factory=dict)

class LogicKnowledgeGraph:
    """Knowledge graph with logical reasoning capabilities."""
    
    def __init__(self):
        """Initialize logic knowledge graph."""
        self.graph = nx.DiGraph()
        self.nodes: Dict[str, LogicNode] = {}
        self.edges: List[LogicEdge] = []
        self.theorems: Dict[str, Formula] = {}
    
    def add_node(self, entity: LogicalEntity) -> str:
        """Add a node to the graph.
        
        Args:
            entity: Logical entity
            
        Returns:
            Node ID
        """
        node_id = f"{entity.entity_type.value}_{len(self.nodes)}"
        node = LogicNode(id=node_id, entity=entity, formula=entity.formula)
        
        self.nodes[node_id] = node
        self.graph.add_node(node_id, **{
            'text': entity.text,
            'type': entity.entity_type.value,
            'confidence': entity.confidence
        })
        
        return node_id
    
    def add_edge(self, relationship: LogicalRelationship) -> None:
        """Add an edge to the graph.
        
        Args:
            relationship: Logical relationship
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
        self.graph.add_edge(
            source_id,
            target_id,
            relation=relationship.relation_type,
            confidence=relationship.confidence
        )
    
    def _find_or_create_node(self, entity: LogicalEntity) -> str:
        """Find existing node or create new one."""
        # Try to find existing node with same text
        for node_id, node in self.nodes.items():
            if node.entity.text == entity.text:
                return node_id
        
        # Create new node
        return self.add_node(entity)
    
    def add_theorem(self, name: str, formula: Formula, proven: bool = True) -> None:
        """Add a proven theorem to the graph.
        
        Args:
            name: Theorem name
            formula: Theorem formula
            proven: Whether the theorem is proven
        """
        self.theorems[name] = formula
        
        # Add as special node in graph
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
            Tuple of (is_consistent, list of inconsistencies)
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
                        f"Contradictory obligations: {obl1.entity.text} vs {obl2.entity.text}"
                    )
        
        # Check obligations vs prohibitions
        prohibitions = [
            node for node in self.nodes.values()
            if node.entity.entity_type == LogicalEntityType.PROHIBITION
        ]
        
        for obl in obligations:
            for proh in prohibitions:
                if self._conflict(obl, proh):
                    inconsistencies.append(
                        f"Obligation conflicts with prohibition: {obl.entity.text} vs {proh.entity.text}"
                    )
        
        is_consistent = len(inconsistencies) == 0
        return is_consistent, inconsistencies
    
    def _are_contradictory(self, node1: LogicNode, node2: LogicNode) -> bool:
        """Check if two nodes are contradictory."""
        # Simple heuristic: opposite text patterns
        text1 = node1.entity.text.lower()
        text2 = node2.entity.text.lower()
        
        # Check for negation patterns
        if "not" in text1 and text1.replace("not", "").strip() == text2:
            return True
        if "not" in text2 and text2.replace("not", "").strip() == text1:
            return True
        
        return False
    
    def _conflict(self, obl: LogicNode, proh: LogicNode) -> bool:
        """Check if obligation conflicts with prohibition."""
        # Extract action from both
        obl_text = obl.entity.text.lower()
        proh_text = proh.entity.text.lower()
        
        # Remove modal words
        obl_action = obl_text.replace("must", "").replace("shall", "").strip()
        proh_action = proh_text.replace("forbidden", "").replace("must not", "").strip()
        
        # Check if same action
        return obl_action == proh_action
    
    def query(self, query_text: str) -> List[LogicNode]:
        """Query the knowledge graph.
        
        Args:
            query_text: Query text
            
        Returns:
            Relevant nodes
        """
        results = []
        
        # Simple keyword matching
        query_lower = query_text.lower()
        for node in self.nodes.values():
            if query_lower in node.entity.text.lower():
                results.append(node)
        
        return results
    
    def get_related_theorems(self, node_id: str) -> List[Tuple[str, Formula]]:
        """Get theorems related to a node.
        
        Args:
            node_id: Node ID
            
        Returns:
            List of (theorem_name, formula) tuples
        """
        related = []
        node = self.nodes.get(node_id)
        if not node or not node.formula:
            return related
        
        # Find theorems that mention similar predicates
        # TODO: Implement more sophisticated matching
        for name, theorem in self.theorems.items():
            related.append((name, theorem))
        
        return related
    
    def export_to_dict(self) -> Dict:
        """Export graph to dictionary format."""
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
```

---

## Week 8: Advanced Integration & Testing

### Day 1-2: Integration with Existing RAG

#### File: `ipfs_datasets_py/rag/logic_enhanced_rag.py`

```python
"""Logic-enhanced Retrieval-Augmented Generation."""

from typing import List, Dict, Optional
from dataclasses import dataclass

from ipfs_datasets_py.rag.logic_knowledge_graph import LogicKnowledgeGraph
from ipfs_datasets_py.rag.logic_aware_entity_extractor import LogicAwareEntityExtractor
from ipfs_datasets_py.logic.TDFOL import Formula, parse_tdfol
from ipfs_datasets_py.logic.integration import NeurosymbolicReasoner

@dataclass
class LogicEnhancedQuery:
    """A query enhanced with logical reasoning."""
    text: str
    logical_entities: List
    relevant_theorems: List[Formula]
    consistency_check: bool
    reasoning_chain: List[str]

class LogicEnhancedRAG:
    """RAG system enhanced with logical reasoning."""
    
    def __init__(self):
        """Initialize logic-enhanced RAG."""
        self.kg = LogicKnowledgeGraph()
        self.extractor = LogicAwareEntityExtractor()
        self.reasoner = NeurosymbolicReasoner()
    
    def ingest_document(self, text: str, doc_id: str) -> None:
        """Ingest a document into the knowledge graph.
        
        Args:
            text: Document text
            doc_id: Document ID
        """
        # Extract entities
        entities = self.extractor.extract_entities(text)
        
        # Extract relationships
        relationships = self.extractor.extract_relationships(text, entities)
        
        # Add to knowledge graph
        for entity in entities:
            self.kg.add_node(entity)
        
        for rel in relationships:
            self.kg.add_edge(rel)
        
        # Check consistency
        is_consistent, inconsistencies = self.kg.check_consistency()
        if not is_consistent:
            print(f"Warning: Inconsistencies found in {doc_id}:")
            for inc in inconsistencies:
                print(f"  - {inc}")
    
    def query(self, query_text: str) -> LogicEnhancedQuery:
        """Query with logical reasoning.
        
        Args:
            query_text: Query text
            
        Returns:
            Logic-enhanced query result
        """
        # Extract entities from query
        query_entities = self.extractor.extract_entities(query_text)
        
        # Find relevant nodes in knowledge graph
        relevant_nodes = self.kg.query(query_text)
        
        # Get related theorems
        relevant_theorems = []
        for node in relevant_nodes:
            theorems = self.kg.get_related_theorems(node.id)
            relevant_theorems.extend([t[1] for t in theorems])
        
        # Check consistency
        is_consistent, _ = self.kg.check_consistency()
        
        # Build reasoning chain
        reasoning_chain = [
            f"Found {len(relevant_nodes)} relevant concepts",
            f"Retrieved {len(relevant_theorems)} related theorems",
            f"Knowledge graph is {'consistent' if is_consistent else 'inconsistent'}"
        ]
        
        return LogicEnhancedQuery(
            text=query_text,
            logical_entities=query_entities,
            relevant_theorems=relevant_theorems,
            consistency_check=is_consistent,
            reasoning_chain=reasoning_chain
        )
```

### Day 3-4: Testing & Examples

#### File: `tests/unit_tests/rag/test_logic_enhanced_rag.py`

```python
"""Tests for logic-enhanced RAG."""

import pytest
from ipfs_datasets_py.rag.logic_enhanced_rag import LogicEnhancedRAG

class TestLogicEnhancedRAG:
    """Test logic-enhanced RAG system."""
    
    def test_ingest_simple_contract(self):
        """Test ingesting a simple contract."""
        rag = LogicEnhancedRAG()
        
        contract_text = """
        Alice must pay Bob $100 within 30 days.
        Bob shall deliver goods to Alice within 7 days.
        """
        
        rag.ingest_document(contract_text, "contract_001")
        
        # Check entities were extracted
        assert len(rag.kg.nodes) > 0
    
    def test_query_obligations(self):
        """Test querying for obligations."""
        rag = LogicEnhancedRAG()
        
        contract_text = """
        The seller must deliver products within 14 days.
        The buyer must pay within 30 days.
        """
        
        rag.ingest_document(contract_text, "contract_002")
        
        # Query for obligations
        result = rag.query("What are the payment obligations?")
        
        assert result.text == "What are the payment obligations?"
        assert len(result.logical_entities) >= 0
    
    def test_consistency_check(self):
        """Test consistency checking."""
        rag = LogicEnhancedRAG()
        
        # Contradictory text
        text = """
        Alice must submit the report.
        Alice must not submit the report.
        """
        
        rag.ingest_document(text, "doc_001")
        
        # Should detect inconsistency
        is_consistent, inconsistencies = rag.kg.check_consistency()
        assert not is_consistent
        assert len(inconsistencies) > 0
```

#### File: `examples/graphrag/logic_enhanced_rag_demo.py`

```python
"""Demo of logic-enhanced RAG system."""

from ipfs_datasets_py.rag.logic_enhanced_rag import LogicEnhancedRAG

def main():
    """Run demo."""
    print("Logic-Enhanced RAG Demo")
    print("=" * 60)
    
    # Create RAG system
    rag = LogicEnhancedRAG()
    
    # Ingest sample contract
    contract = """
    Service Level Agreement
    
    Provider obligations:
    - Provider must maintain 99.9% uptime
    - Provider must respond to incidents within 4 hours
    - Provider shall provide monthly reports
    
    Client obligations:
    - Client must pay monthly fee within 15 days
    - Client may terminate with 30 days notice
    
    Prohibitions:
    - Provider must not share client data
    - Client must not reverse engineer the system
    """
    
    print("\n1. Ingesting contract...")
    rag.ingest_document(contract, "sla_001")
    print(f"   Created {len(rag.kg.nodes)} nodes in knowledge graph")
    
    # Check consistency
    print("\n2. Checking consistency...")
    is_consistent, inconsistencies = rag.kg.check_consistency()
    if is_consistent:
        print("   ✓ Knowledge graph is consistent")
    else:
        print("   ✗ Inconsistencies found:")
        for inc in inconsistencies:
            print(f"     - {inc}")
    
    # Query
    print("\n3. Querying: 'What are provider obligations?'")
    result = rag.query("What are provider obligations?")
    print(f"   Found {len(result.logical_entities)} relevant entities")
    print("\n   Reasoning chain:")
    for step in result.reasoning_chain:
        print(f"     - {step}")
    
    # Export graph
    print("\n4. Exporting knowledge graph...")
    graph_data = rag.kg.export_to_dict()
    print(f"   Nodes: {len(graph_data['nodes'])}")
    print(f"   Edges: {len(graph_data['edges'])}")
    print(f"   Theorems: {len(graph_data['theorems'])}")
    
    print("\n" + "=" * 60)
    print("Demo complete!")

if __name__ == "__main__":
    main()
```

### Day 5: Documentation & Integration

#### Update: `docs/GRAPHRAG_INTEGRATION.md`

```markdown
# GraphRAG Integration Guide

## Overview

The logic module now integrates with GraphRAG to provide:
- Logic-aware entity extraction
- Theorem-augmented knowledge graphs
- Consistency checking
- Enhanced query understanding

## Quick Start

```python
from ipfs_datasets_py.rag import LogicEnhancedRAG

# Create RAG system
rag = LogicEnhancedRAG()

# Ingest document
rag.ingest_document(document_text, doc_id="doc_001")

# Query with reasoning
result = rag.query("What are the obligations?")
print(result.reasoning_chain)
```

## Features

### 1. Logic-Aware Entity Extraction

Automatically extracts:
- Agents (people, organizations)
- Obligations (must, shall, required to)
- Permissions (may, allowed to, can)
- Prohibitions (forbidden, must not)
- Temporal constraints (within X days, always)
- Conditionals (if...then)

### 2. Knowledge Graph Construction

Creates graph with:
- Nodes for each entity
- Edges for relationships
- Logical formulas attached to nodes
- Proven theorems as special nodes

### 3. Consistency Checking

Detects:
- Contradictory obligations
- Conflicts between obligations and prohibitions
- Logical inconsistencies

### 4. Enhanced Querying

Provides:
- Relevant entities
- Related theorems
- Reasoning chain
- Consistency status

## API Reference

See individual module documentation.
```

---

## Testing Strategy

### Unit Tests (15+ tests)
- Entity extractor: 5 tests
- Knowledge graph: 5 tests
- Logic-enhanced RAG: 5 tests

### Integration Tests (5+ tests)
- End-to-end document ingestion
- Query with reasoning
- Consistency checking workflow

### Performance Tests (3 tests)
- Large document ingestion (<1s)
- Query performance (<100ms)
- Graph operations (<10ms)

---

## Success Criteria

- [ ] All unit tests passing
- [ ] Integration tests passing
- [ ] Performance targets met
- [ ] Documentation complete
- [ ] Examples working
- [ ] Integrated with existing RAG system

---

## Next Steps

1. Review this plan with team
2. Begin implementation Week 7
3. Daily standups to track progress
4. Demo at end of Week 8
5. Gather feedback for iteration

**Status:** Ready for implementation! 🚀
