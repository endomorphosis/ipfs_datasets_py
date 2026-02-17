"""
Legal GraphRAG Integration for Search Results.

This module bridges legal search results with the existing GraphRAG infrastructure,
enabling automatic knowledge graph construction, entity extraction, semantic search,
and graph-based result ranking.

Features:
- Automatic knowledge graph construction from search results
- Entity and relationship extraction from legal documents
- Semantic search over legal knowledge graph
- Query-driven subgraph extraction
- Graph-based result ranking and clustering
- Integration with existing GraphRAG module

Usage:
    from ipfs_datasets_py.processors.legal_scrapers import LegalGraphRAG
    
    graphrag = LegalGraphRAG()
    
    # Build knowledge graph from search results
    kg = graphrag.build_knowledge_graph(search_results)
    
    # Semantic search over graph
    results = graphrag.semantic_search(query="EPA regulations", top_k=10)
    
    # Extract subgraph
    subgraph = graphrag.extract_subgraph(query="water pollution", max_depth=2)
"""

import logging
from typing import List, Dict, Optional, Any, Set, Tuple
from dataclasses import dataclass, field

# Import existing GraphRAG infrastructure
try:
    from ipfs_datasets_py.search.graphrag_integration import GraphRAGFactory
    from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import (
        Entity,
        Relationship,
        KnowledgeGraph,
        KnowledgeGraphExtractor
    )
    HAVE_GRAPHRAG = True
except ImportError:
    HAVE_GRAPHRAG = False
    GraphRAGFactory = None
    Entity = None
    Relationship = None
    KnowledgeGraph = None
    KnowledgeGraphExtractor = None

logger = logging.getLogger(__name__)


@dataclass
class LegalEntity(Entity if Entity else object):
    """Legal-specific entity with jurisdiction and legal type."""
    jurisdiction: Optional[str] = None  # federal/state/local
    legal_type: Optional[str] = None  # regulation/statute/case/agency
    citation: Optional[str] = None


@dataclass
class LegalRelationship:
    """Relationship between legal entities."""
    source_entity: str
    target_entity: str
    relationship_type: str  # "regulates", "enforces", "cites", "amends"
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LegalKnowledgeGraph:
    """Knowledge graph for legal search results."""
    entities: List[LegalEntity] = field(default_factory=list)
    relationships: List[LegalRelationship] = field(default_factory=list)
    sources: List[Dict[str, Any]] = field(default_factory=list)  # Original search results
    
    def add_entity(self, entity: LegalEntity):
        """Add entity to graph."""
        self.entities.append(entity)
    
    def add_relationship(self, relationship: LegalRelationship):
        """Add relationship to graph."""
        self.relationships.append(relationship)
    
    def get_entity_by_name(self, name: str) -> Optional[LegalEntity]:
        """Find entity by name."""
        for entity in self.entities:
            if entity.name.lower() == name.lower():
                return entity
        return None
    
    def get_neighbors(self, entity_name: str, max_depth: int = 1) -> Set[str]:
        """Get neighboring entities up to max_depth."""
        neighbors = set()
        current_level = {entity_name}
        visited = set()
        
        for _ in range(max_depth):
            next_level = set()
            for node in current_level:
                if node in visited:
                    continue
                visited.add(node)
                
                # Find relationships
                for rel in self.relationships:
                    if rel.source_entity == node:
                        next_level.add(rel.target_entity)
                    elif rel.target_entity == node:
                        next_level.add(rel.source_entity)
            
            neighbors.update(next_level)
            current_level = next_level
        
        return neighbors - {entity_name}


class LegalGraphRAG:
    """
    Legal GraphRAG integration for search results.
    
    Bridges legal search with existing GraphRAG infrastructure to provide:
    - Automatic knowledge graph construction from search results
    - Entity and relationship extraction
    - Semantic search over legal knowledge graph
    - Query-driven subgraph extraction
    - Graph-based result ranking
    
    Example:
        >>> graphrag = LegalGraphRAG()
        >>> kg = graphrag.build_knowledge_graph(search_results)
        >>> results = graphrag.semantic_search("EPA water regulations")
        >>> subgraph = graphrag.extract_subgraph("clean water act", max_depth=2)
    """
    
    def __init__(
        self,
        use_existing_graphrag: bool = True,
        extraction_model: Optional[str] = None
    ):
        """Initialize Legal GraphRAG.
        
        Args:
            use_existing_graphrag: Whether to use existing GraphRAG infrastructure
            extraction_model: Model to use for entity extraction
        """
        self.use_existing_graphrag = use_existing_graphrag and HAVE_GRAPHRAG
        self.extraction_model = extraction_model
        
        # Initialize extractor if GraphRAG available
        if self.use_existing_graphrag:
            try:
                self.extractor = KnowledgeGraphExtractor(model_name=extraction_model)
            except Exception as e:
                logger.warning(f"Failed to initialize KnowledgeGraphExtractor: {e}")
                self.extractor = None
        else:
            self.extractor = None
        
        # Store built knowledge graph
        self.knowledge_graph: Optional[LegalKnowledgeGraph] = None
        
        logger.info(f"LegalGraphRAG initialized (GraphRAG available: {HAVE_GRAPHRAG})")
    
    def build_knowledge_graph(
        self,
        results: List[Dict[str, Any]],
        extract_entities: bool = True,
        extract_relationships: bool = True
    ) -> LegalKnowledgeGraph:
        """
        Build knowledge graph from search results.
        
        Args:
            results: Search results to build graph from
            extract_entities: Whether to extract entities
            extract_relationships: Whether to extract relationships
            
        Returns:
            LegalKnowledgeGraph
        """
        kg = LegalKnowledgeGraph()
        
        # Store original sources
        kg.sources = results
        
        if not extract_entities:
            return kg
        
        # Extract entities and relationships from each result
        for i, result in enumerate(results):
            title = result.get("title", "")
            snippet = result.get("snippet", result.get("description", ""))
            url = result.get("url", "")
            domain = result.get("domain", "")
            
            # Combine title and snippet for extraction
            text = f"{title}. {snippet}"
            
            # Extract entities
            entities = self._extract_entities_from_text(text, url, domain)
            for entity in entities:
                kg.add_entity(entity)
            
            # Extract relationships if requested
            if extract_relationships and len(entities) > 1:
                relationships = self._extract_relationships_from_entities(entities, text)
                for rel in relationships:
                    kg.add_relationship(rel)
        
        # Store built graph
        self.knowledge_graph = kg
        
        logger.info(f"Built knowledge graph: {len(kg.entities)} entities, {len(kg.relationships)} relationships")
        
        return kg
    
    def _extract_entities_from_text(
        self,
        text: str,
        url: str,
        domain: str
    ) -> List[LegalEntity]:
        """Extract legal entities from text."""
        entities = []
        
        if self.extractor:
            try:
                # Use existing GraphRAG extractor
                kg = self.extractor.extract_from_text(text)
                
                # Convert to LegalEntity
                for entity in kg.entities:
                    legal_entity = LegalEntity(
                        entity_id=entity.entity_id,
                        entity_type=entity.entity_type,
                        name=entity.name,
                        properties=entity.properties,
                        confidence=entity.confidence,
                        source_text=entity.source_text,
                        jurisdiction=self._detect_jurisdiction_from_text(text),
                        legal_type=self._detect_legal_type(entity.name, text)
                    )
                    entities.append(legal_entity)
            
            except Exception as e:
                logger.warning(f"GraphRAG extraction failed: {e}, using rule-based fallback")
                entities = self._rule_based_entity_extraction(text, url, domain)
        else:
            # Fallback to rule-based extraction
            entities = self._rule_based_entity_extraction(text, url, domain)
        
        return entities
    
    def _rule_based_entity_extraction(
        self,
        text: str,
        url: str,
        domain: str
    ) -> List[LegalEntity]:
        """Rule-based entity extraction for fallback."""
        entities = []
        
        # Common legal entity patterns
        patterns = {
            "agency": r'\b(EPA|OSHA|FDA|SEC|FTC|DOJ|HHS)\b',
            "regulation": r'\b(\d+\s+(?:CFR|C\.F\.R\.))\b',
            "statute": r'\b(\d+\s+(?:USC|U\.S\.C\.))\b',
            "case": r'\b(\d+\s+(?:F\.\s?(?:2d|3d)|U\.S\.))\b',
        }
        
        import re
        entity_id_counter = 0
        
        for entity_type, pattern in patterns.items():
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                name = match.group(0)
                entity = LegalEntity(
                    entity_id=f"entity_{entity_id_counter}",
                    entity_type=entity_type,
                    name=name,
                    confidence=0.8,
                    source_text=text,
                    jurisdiction=self._detect_jurisdiction_from_text(text),
                    legal_type=entity_type
                )
                entities.append(entity)
                entity_id_counter += 1
        
        return entities
    
    def _detect_jurisdiction_from_text(self, text: str) -> str:
        """Detect jurisdiction from text."""
        text_lower = text.lower()
        
        if any(term in text_lower for term in ["federal", "u.s.", "united states"]):
            return "federal"
        elif any(term in text_lower for term in ["state", "california", "texas", "new york"]):
            return "state"
        elif any(term in text_lower for term in ["city", "county", "municipal"]):
            return "local"
        else:
            return "unknown"
    
    def _detect_legal_type(self, entity_name: str, text: str) -> str:
        """Detect legal type of entity."""
        name_lower = entity_name.lower()
        
        if "cfr" in name_lower or "c.f.r" in name_lower:
            return "regulation"
        elif "usc" in name_lower or "u.s.c" in name_lower:
            return "statute"
        elif any(term in name_lower for term in ["f.2d", "f.3d", "u.s."]):
            return "case"
        elif any(agency in entity_name for agency in ["EPA", "OSHA", "FDA", "SEC"]):
            return "agency"
        else:
            return "entity"
    
    def _extract_relationships_from_entities(
        self,
        entities: List[LegalEntity],
        text: str
    ) -> List[LegalRelationship]:
        """Extract relationships between entities."""
        relationships = []
        
        # Simple rule-based relationship extraction
        relationship_patterns = {
            "regulates": r"(\w+)\s+regulates?\s+(\w+)",
            "enforces": r"(\w+)\s+enforces?\s+(\w+)",
            "cites": r"(\w+)\s+(?:cites?|references?)\s+(\w+)",
            "amends": r"(\w+)\s+amends?\s+(\w+)",
        }
        
        import re
        
        for rel_type, pattern in relationship_patterns.items():
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                source = match.group(1)
                target = match.group(2)
                
                # Check if entities exist
                source_entity = next((e for e in entities if source.lower() in e.name.lower()), None)
                target_entity = next((e for e in entities if target.lower() in e.name.lower()), None)
                
                if source_entity and target_entity:
                    relationship = LegalRelationship(
                        source_entity=source_entity.name,
                        target_entity=target_entity.name,
                        relationship_type=rel_type,
                        confidence=0.7
                    )
                    relationships.append(relationship)
        
        return relationships
    
    def semantic_search(
        self,
        query: str,
        top_k: int = 10,
        use_graph_traversal: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Semantic search over knowledge graph.
        
        Args:
            query: Search query
            top_k: Number of results to return
            use_graph_traversal: Whether to use graph traversal
            
        Returns:
            List of search results with graph context
        """
        if not self.knowledge_graph:
            logger.warning("No knowledge graph built, call build_knowledge_graph first")
            return []
        
        results = []
        
        # Simple semantic search based on entity matching
        query_lower = query.lower()
        
        for entity in self.knowledge_graph.entities:
            if query_lower in entity.name.lower():
                # Find related entities
                neighbors = self.knowledge_graph.get_neighbors(entity.name, max_depth=1)
                
                result = {
                    "entity": entity,
                    "relevance_score": entity.confidence,
                    "neighbors": list(neighbors),
                    "relationships": [
                        r for r in self.knowledge_graph.relationships
                        if r.source_entity == entity.name or r.target_entity == entity.name
                    ]
                }
                results.append(result)
        
        # Sort by relevance
        results.sort(key=lambda x: x["relevance_score"], reverse=True)
        
        return results[:top_k]
    
    def extract_subgraph(
        self,
        query: str,
        max_depth: int = 2,
        min_confidence: float = 0.5
    ) -> LegalKnowledgeGraph:
        """
        Extract subgraph relevant to query.
        
        Args:
            query: Query to extract subgraph for
            max_depth: Maximum depth of graph traversal
            min_confidence: Minimum entity confidence threshold
            
        Returns:
            Subgraph as LegalKnowledgeGraph
        """
        if not self.knowledge_graph:
            logger.warning("No knowledge graph built")
            return LegalKnowledgeGraph()
        
        subgraph = LegalKnowledgeGraph()
        query_lower = query.lower()
        
        # Find seed entities matching query
        seed_entities = [
            e for e in self.knowledge_graph.entities
            if query_lower in e.name.lower() and e.confidence >= min_confidence
        ]
        
        if not seed_entities:
            return subgraph
        
        # Collect entities within max_depth
        entity_names = set()
        for seed in seed_entities:
            entity_names.add(seed.name)
            neighbors = self.knowledge_graph.get_neighbors(seed.name, max_depth)
            entity_names.update(neighbors)
        
        # Add entities to subgraph
        for entity in self.knowledge_graph.entities:
            if entity.name in entity_names:
                subgraph.add_entity(entity)
        
        # Add relationships
        for rel in self.knowledge_graph.relationships:
            if rel.source_entity in entity_names and rel.target_entity in entity_names:
                subgraph.add_relationship(rel)
        
        logger.info(f"Extracted subgraph: {len(subgraph.entities)} entities, {len(subgraph.relationships)} relationships")
        
        return subgraph
    
    def rank_results_by_graph(
        self,
        results: List[Dict[str, Any]],
        query: str
    ) -> List[Dict[str, Any]]:
        """
        Rank results using graph-based scoring.
        
        Args:
            results: Search results to rank
            query: Query string
            
        Returns:
            Ranked results
        """
        if not self.knowledge_graph:
            return results
        
        # Calculate graph scores
        for result in results:
            url = result.get("url", "")
            
            # Find entities from this source
            source_entities = [
                e for e in self.knowledge_graph.entities
                if url in str(e.properties.get("source_url", ""))
            ]
            
            # Score based on entity count and relationships
            entity_count = len(source_entities)
            relationship_count = sum(
                1 for e in source_entities
                for r in self.knowledge_graph.relationships
                if r.source_entity == e.name or r.target_entity == e.name
            )
            
            # Calculate graph score
            graph_score = (entity_count * 0.6 + relationship_count * 0.4) / max(entity_count, 1)
            result["graph_score"] = min(graph_score, 1.0)
        
        # Sort by graph score
        results.sort(key=lambda x: x.get("graph_score", 0), reverse=True)
        
        return results
    
    def visualize_graph(
        self,
        format: str = "mermaid",
        max_entities: int = 50
    ) -> str:
        """
        Generate visualization of knowledge graph.
        
        Args:
            format: Visualization format ("mermaid", "dot")
            max_entities: Maximum number of entities to include
            
        Returns:
            Visualization string
        """
        if not self.knowledge_graph:
            return ""
        
        if format == "mermaid":
            return self._generate_mermaid_graph(max_entities)
        elif format == "dot":
            return self._generate_dot_graph(max_entities)
        else:
            return f"Unsupported format: {format}"
    
    def _generate_mermaid_graph(self, max_entities: int) -> str:
        """Generate Mermaid graph visualization."""
        lines = ["graph TD"]
        
        # Add entities (nodes)
        entities = self.knowledge_graph.entities[:max_entities]
        for entity in entities:
            node_id = entity.entity_id or entity.name.replace(" ", "_")
            label = f"{entity.name} ({entity.entity_type})"
            lines.append(f"    {node_id}[\"{label}\"]")
        
        # Add relationships (edges)
        entity_ids = {e.name for e in entities}
        for rel in self.knowledge_graph.relationships:
            if rel.source_entity in entity_ids and rel.target_entity in entity_ids:
                source_id = rel.source_entity.replace(" ", "_")
                target_id = rel.target_entity.replace(" ", "_")
                label = rel.relationship_type
                lines.append(f"    {source_id} -->|{label}| {target_id}")
        
        return "\n".join(lines)
    
    def _generate_dot_graph(self, max_entities: int) -> str:
        """Generate DOT graph visualization."""
        lines = ["digraph LegalKG {"]
        
        # Add entities
        entities = self.knowledge_graph.entities[:max_entities]
        for entity in entities:
            node_id = entity.entity_id or entity.name.replace(" ", "_")
            label = f"{entity.name}\\n{entity.entity_type}"
            lines.append(f'    {node_id} [label="{label}"];')
        
        # Add relationships
        entity_ids = {e.name for e in entities}
        for rel in self.knowledge_graph.relationships:
            if rel.source_entity in entity_ids and rel.target_entity in entity_ids:
                source_id = rel.source_entity.replace(" ", "_")
                target_id = rel.target_entity.replace(" ", "_")
                label = rel.relationship_type
                lines.append(f'    {source_id} -> {target_id} [label="{label}"];')
        
        lines.append("}")
        return "\n".join(lines)
