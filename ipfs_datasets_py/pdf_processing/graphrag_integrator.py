"""
GraphRAG Integration Module for PDF Processing Pipeline

Integrates processed PDF content into GraphRAG knowledge graph:
- Creates entity-relationship structures
- Builds knowledge graph representations
- Supports cross-document relationship discovery
- Enables semantic querying and retrieval
- Maintains IPLD data integrity
"""

import asyncio
import logging
import json
import hashlib
from typing import Dict, List, Any, Optional, Union, Set, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
import uuid

import networkx as nx
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from ..ipld import IPLDStorage
from ..audit import AuditLogger
from .llm_optimizer import LLMDocument, LLMChunk

logger = logging.getLogger(__name__)

@dataclass
class Entity:
    """Represents an entity in the knowledge graph."""
    id: str
    name: str
    type: str  # 'person', 'organization', 'concept', 'location', etc.
    description: str
    confidence: float
    source_chunks: List[str]  # Chunk IDs where entity appears
    properties: Dict[str, Any]
    embedding: Optional[np.ndarray] = None

@dataclass
class Relationship:
    """Represents a relationship between entities."""
    id: str
    source_entity_id: str
    target_entity_id: str
    relationship_type: str
    description: str
    confidence: float
    source_chunks: List[str]
    properties: Dict[str, Any]

@dataclass
class KnowledgeGraph:
    """Complete knowledge graph representation."""
    graph_id: str
    document_id: str
    entities: List[Entity]
    relationships: List[Relationship]
    chunks: List[LLMChunk]
    metadata: Dict[str, Any]
    creation_timestamp: str
    ipld_cid: Optional[str] = None

@dataclass
class CrossDocumentRelationship:
    """Relationship spanning multiple documents."""
    id: str
    source_document_id: str
    target_document_id: str
    source_entity_id: str
    target_entity_id: str
    relationship_type: str
    confidence: float
    evidence_chunks: List[str]

class GraphRAGIntegrator:
    """
    Integrates PDF content into GraphRAG knowledge structures.
    """
    
    def __init__(self, 
                 storage: Optional[IPLDStorage] = None,
                 similarity_threshold: float = 0.8,
                 entity_extraction_confidence: float = 0.6):
        """
        Initialize the GraphRAG integrator.
        
        Args:
            storage: IPLD storage instance
            similarity_threshold: Threshold for entity similarity matching
            entity_extraction_confidence: Minimum confidence for entity extraction
        """
        self.storage = storage or IPLDStorage()
        self.similarity_threshold = similarity_threshold
        self.entity_extraction_confidence = entity_extraction_confidence
        
        # Graph storage
        self.knowledge_graphs: Dict[str, KnowledgeGraph] = {}
        self.global_entities: Dict[str, Entity] = {}
        self.cross_document_relationships: List[CrossDocumentRelationship] = []
        
        # NetworkX graphs for analysis
        self.document_graphs: Dict[str, nx.DiGraph] = {}
        self.global_graph = nx.DiGraph()
        
    async def integrate_document(self, llm_document: LLMDocument) -> KnowledgeGraph:
        """
        Integrate an LLM-optimized document into the GraphRAG system.
        
        Args:
            llm_document: Optimized document from LLM processing
            
        Returns:
            KnowledgeGraph representing the document
        """
        logger.info(f"Starting GraphRAG integration for document: {llm_document.document_id}")
        
        # Extract entities from chunks
        entities = await self._extract_entities_from_chunks(llm_document.chunks)
        
        # Extract relationships
        relationships = await self._extract_relationships(entities, llm_document.chunks)
        
        # Create knowledge graph
        knowledge_graph = KnowledgeGraph(
            graph_id=f"kg_{llm_document.document_id}_{uuid.uuid4().hex[:8]}",
            document_id=llm_document.document_id,
            entities=entities,
            relationships=relationships,
            chunks=llm_document.chunks,
            metadata={
                'document_title': llm_document.title,
                'entity_count': len(entities),
                'relationship_count': len(relationships),
                'chunk_count': len(llm_document.chunks),
                'processing_timestamp': datetime.utcnow().isoformat()
            },
            creation_timestamp=datetime.utcnow().isoformat()
        )
        
        # Store in IPLD
        ipld_cid = await self._store_knowledge_graph_ipld(knowledge_graph)
        knowledge_graph.ipld_cid = ipld_cid
        
        # Update internal storage
        self.knowledge_graphs[knowledge_graph.graph_id] = knowledge_graph
        
        # Create NetworkX representation
        nx_graph = await self._create_networkx_graph(knowledge_graph)
        self.document_graphs[llm_document.document_id] = nx_graph
        
        # Merge with global graph
        await self._merge_into_global_graph(knowledge_graph)
        
        # Discover cross-document relationships
        await self._discover_cross_document_relationships(knowledge_graph)
        
        logger.info(f"GraphRAG integration complete: {len(entities)} entities, {len(relationships)} relationships")
        return knowledge_graph
    
    async def _extract_entities_from_chunks(self, chunks: List[LLMChunk]) -> List[Entity]:
        """Extract entities from LLM chunks."""
        entities = []
        entity_mentions = {}  # Track entity mentions across chunks
        
        for chunk in chunks:
            # Extract entities from chunk content
            chunk_entities = await self._extract_entities_from_text(
                chunk.content, 
                chunk.chunk_id
            )
            
            for entity_data in chunk_entities:
                entity_key = (entity_data['name'].lower(), entity_data['type'])
                
                if entity_key in entity_mentions:
                    # Update existing entity
                    existing_entity = entity_mentions[entity_key]
                    existing_entity.source_chunks.append(chunk.chunk_id)
                    existing_entity.confidence = max(existing_entity.confidence, entity_data['confidence'])
                    
                    # Merge properties
                    for key, value in entity_data.get('properties', {}).items():
                        if key not in existing_entity.properties:
                            existing_entity.properties[key] = value
                else:
                    # Create new entity
                    entity_id = f"entity_{hashlib.md5(f'{entity_data['name']}_{entity_data['type']}'.encode()).hexdigest()[:8]}"
                    
                    entity = Entity(
                        id=entity_id,
                        name=entity_data['name'],
                        type=entity_data['type'],
                        description=entity_data.get('description', ''),
                        confidence=entity_data['confidence'],
                        source_chunks=[chunk.chunk_id],
                        properties=entity_data.get('properties', {}),
                        embedding=entity_data.get('embedding')
                    )
                    
                    entity_mentions[entity_key] = entity
                    entities.append(entity)
        
        # Filter entities by confidence
        filtered_entities = [
            entity for entity in entities 
            if entity.confidence >= self.entity_extraction_confidence
        ]
        
        logger.info(f"Extracted {len(filtered_entities)} entities from {len(chunks)} chunks")
        return filtered_entities
    
    async def _extract_entities_from_text(self, text: str, chunk_id: str) -> List[Dict[str, Any]]:
        """Extract entities from a single text chunk."""
        entities = []
        
        # Named Entity Recognition patterns (can be enhanced with NLP models)
        patterns = {
            'person': [
                r'\b[A-Z][a-z]+ [A-Z][a-z]+\b',  # John Smith
                r'\b(?:Dr|Mr|Ms|Mrs|Prof)\.?\s+[A-Z][a-z]+ [A-Z][a-z]+\b'  # Dr. John Smith
            ],
            'organization': [
                r'\b[A-Z][a-z]+ (?:Inc|Corp|LLC|Ltd|Company|Corporation)\b',
                r'\b[A-Z][A-Z]+ [A-Z][a-z]+\b',  # IBM Corp
                r'\b[A-Z][a-z]+ University\b'
            ],
            'location': [
                r'\b[A-Z][a-z]+(?:,\s*[A-Z][a-z]+)*(?:,\s*[A-Z]{2})\b',  # City, State
                r'\b[A-Z][a-z]+ (?:Street|Avenue|Road|Boulevard|Drive)\b'
            ],
            'date': [
                r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b',
                r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b'
            ],
            'currency': [
                r'\$\d{1,3}(?:,\d{3})*(?:\.\d{2})?\b',
                r'\b\d{1,3}(?:,\d{3})*(?:\.\d{2})?\s*(?:dollars|USD|cents)\b'
            ]
        }
        
        for entity_type, type_patterns in patterns.items():
            for pattern in type_patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                for match in matches:
                    if len(match.strip()) > 2:  # Minimum length filter
                        entities.append({
                            'name': match.strip(),
                            'type': entity_type,
                            'description': f'{entity_type.capitalize()} found in chunk {chunk_id}',
                            'confidence': 0.7,  # Base confidence for pattern matching
                            'properties': {
                                'extraction_method': 'pattern_matching',
                                'source_chunk': chunk_id
                            }
                        })
        
        # Remove duplicates
        unique_entities = []
        seen_names = set()
        for entity in entities:
            name_key = entity['name'].lower()
            if name_key not in seen_names:
                seen_names.add(name_key)
                unique_entities.append(entity)
        
        return unique_entities
    
    async def _extract_relationships(self, 
                                   entities: List[Entity], 
                                   chunks: List[LLMChunk]) -> List[Relationship]:
        """Extract relationships between entities."""
        relationships = []
        
        # Build entity index for quick lookup
        entity_by_chunk = {}
        for entity in entities:
            for chunk_id in entity.source_chunks:
                if chunk_id not in entity_by_chunk:
                    entity_by_chunk[chunk_id] = []
                entity_by_chunk[chunk_id].append(entity)
        
        # Extract relationships within chunks
        for chunk in chunks:
            chunk_entities = entity_by_chunk.get(chunk.chunk_id, [])
            if len(chunk_entities) >= 2:
                chunk_relationships = await self._extract_chunk_relationships(
                    chunk_entities, chunk
                )
                relationships.extend(chunk_relationships)
        
        # Extract cross-chunk relationships (same document)
        cross_chunk_relationships = await self._extract_cross_chunk_relationships(
            entities, chunks
        )
        relationships.extend(cross_chunk_relationships)
        
        logger.info(f"Extracted {len(relationships)} relationships")
        return relationships
    
    async def _extract_chunk_relationships(self, 
                                         entities: List[Entity], 
                                         chunk: LLMChunk) -> List[Relationship]:
        """Extract relationships between entities in a single chunk."""
        relationships = []
        
        # Simple co-occurrence based relationships
        for i, entity1 in enumerate(entities):
            for entity2 in entities[i+1:]:
                # Check if entities co-occur in the chunk
                text_lower = chunk.content.lower()
                if (entity1.name.lower() in text_lower and 
                    entity2.name.lower() in text_lower):
                    
                    # Determine relationship type based on context
                    relationship_type = self._infer_relationship_type(
                        entity1, entity2, chunk.content
                    )
                    
                    if relationship_type:
                        rel_id = f"rel_{hashlib.md5(f'{entity1.id}_{entity2.id}_{relationship_type}'.encode()).hexdigest()[:8]}"
                        
                        relationship = Relationship(
                            id=rel_id,
                            source_entity_id=entity1.id,
                            target_entity_id=entity2.id,
                            relationship_type=relationship_type,
                            description=f"{entity1.name} {relationship_type} {entity2.name}",
                            confidence=0.6,  # Base confidence for co-occurrence
                            source_chunks=[chunk.chunk_id],
                            properties={
                                'extraction_method': 'co_occurrence',
                                'context_snippet': chunk.content[:200] + '...' if len(chunk.content) > 200 else chunk.content
                            }
                        )
                        relationships.append(relationship)
        
        return relationships
    
    def _infer_relationship_type(self, entity1: Entity, entity2: Entity, context: str) -> Optional[str]:
        """Infer relationship type between two entities based on context."""
        context_lower = context.lower()
        
        # Person-Organization relationships
        if entity1.type == 'person' and entity2.type == 'organization':
            if any(keyword in context_lower for keyword in ['ceo', 'president', 'director', 'manager']):
                return 'leads'
            elif any(keyword in context_lower for keyword in ['employee', 'works', 'employed']):
                return 'works_for'
            elif any(keyword in context_lower for keyword in ['founded', 'founder']):
                return 'founded'
            else:
                return 'associated_with'
        
        # Organization-Organization relationships
        elif entity1.type == 'organization' and entity2.type == 'organization':
            if any(keyword in context_lower for keyword in ['acquired', 'bought', 'purchased']):
                return 'acquired'
            elif any(keyword in context_lower for keyword in ['partner', 'collaboration', 'joint']):
                return 'partners_with'
            elif any(keyword in context_lower for keyword in ['competitor', 'competes']):
                return 'competes_with'
            else:
                return 'related_to'
        
        # Person-Person relationships
        elif entity1.type == 'person' and entity2.type == 'person':
            if any(keyword in context_lower for keyword in ['colleague', 'team', 'together']):
                return 'collaborates_with'
            elif any(keyword in context_lower for keyword in ['report', 'manages', 'supervises']):
                return 'manages'
            else:
                return 'knows'
        
        # Location relationships
        elif 'location' in [entity1.type, entity2.type]:
            return 'located_in'
        
        # Default relationship
        return 'related_to'
    
    async def _extract_cross_chunk_relationships(self, 
                                               entities: List[Entity], 
                                               chunks: List[LLMChunk]) -> List[Relationship]:
        """Extract relationships between entities across different chunks."""
        relationships = []
        
        # Group entities by type for more efficient processing
        entities_by_type = {}
        for entity in entities:
            if entity.type not in entities_by_type:
                entities_by_type[entity.type] = []
            entities_by_type[entity.type].append(entity)
        
        # Find entities that appear in sequential chunks (narrative relationships)
        chunk_sequences = self._find_chunk_sequences(chunks)
        for seq in chunk_sequences:
            seq_entities = []
            for chunk_id in seq:
                chunk_entities = [e for e in entities if chunk_id in e.source_chunks]
                seq_entities.extend(chunk_entities)
            
            # Create narrative relationships
            if len(seq_entities) >= 2:
                for i, entity1 in enumerate(seq_entities):
                    for entity2 in seq_entities[i+1:]:
                        if entity1.id != entity2.id:
                            rel_id = f"rel_seq_{hashlib.md5(f'{entity1.id}_{entity2.id}'.encode()).hexdigest()[:8]}"
                            
                            relationship = Relationship(
                                id=rel_id,
                                source_entity_id=entity1.id,
                                target_entity_id=entity2.id,
                                relationship_type='narrative_sequence',
                                description=f"{entity1.name} appears in narrative sequence with {entity2.name}",
                                confidence=0.4,
                                source_chunks=list(set(entity1.source_chunks + entity2.source_chunks)),
                                properties={
                                    'extraction_method': 'narrative_sequence',
                                    'sequence_length': len(seq)
                                }
                            )
                            relationships.append(relationship)
        
        return relationships
    
    def _find_chunk_sequences(self, chunks: List[LLMChunk]) -> List[List[str]]:
        """Find sequences of related chunks (e.g., same page, sequential)."""
        sequences = []
        
        # Group chunks by page
        chunks_by_page = {}
        for chunk in chunks:
            page = chunk.source_page
            if page not in chunks_by_page:
                chunks_by_page[page] = []
            chunks_by_page[page].append(chunk.chunk_id)
        
        # Each page is a sequence
        for page, chunk_ids in chunks_by_page.items():
            if len(chunk_ids) > 1:
                sequences.append(chunk_ids)
        
        return sequences
    
    async def _create_networkx_graph(self, knowledge_graph: KnowledgeGraph) -> nx.DiGraph:
        """Create NetworkX graph representation."""
        graph = nx.DiGraph()
        
        # Add entities as nodes
        for entity in knowledge_graph.entities:
            graph.add_node(
                entity.id,
                name=entity.name,
                type=entity.type,
                confidence=entity.confidence,
                source_chunks=entity.source_chunks,
                **entity.properties
            )
        
        # Add relationships as edges
        for relationship in knowledge_graph.relationships:
            graph.add_edge(
                relationship.source_entity_id,
                relationship.target_entity_id,
                relationship_type=relationship.relationship_type,
                confidence=relationship.confidence,
                source_chunks=relationship.source_chunks,
                **relationship.properties
            )
        
        return graph
    
    async def _merge_into_global_graph(self, knowledge_graph: KnowledgeGraph):
        """Merge document knowledge graph into global graph."""
        # Update global entities
        for entity in knowledge_graph.entities:
            if entity.id not in self.global_entities:
                self.global_entities[entity.id] = entity
            else:
                # Merge entity information
                existing = self.global_entities[entity.id]
                existing.source_chunks.extend(entity.source_chunks)
                existing.source_chunks = list(set(existing.source_chunks))
                existing.confidence = max(existing.confidence, entity.confidence)
        
        # Merge into global NetworkX graph
        doc_graph = self.document_graphs[knowledge_graph.document_id]
        self.global_graph = nx.compose(self.global_graph, doc_graph)
    
    async def _discover_cross_document_relationships(self, knowledge_graph: KnowledgeGraph):
        """Discover relationships between entities across documents."""
        if not self.global_entities:
            return
        
        new_relationships = []
        
        for entity in knowledge_graph.entities:
            # Find similar entities in other documents
            similar_entities = await self._find_similar_entities(entity)
            
            for similar_entity in similar_entities:
                if similar_entity.id != entity.id:
                    # Check if they're from different documents
                    entity_docs = set()
                    similar_docs = set()
                    
                    for chunk_id in entity.source_chunks:
                        # Extract document ID from chunk (assuming chunk format includes doc info)
                        entity_docs.add(knowledge_graph.document_id)
                    
                    for chunk_id in similar_entity.source_chunks:
                        # Find document for this chunk
                        for kg in self.knowledge_graphs.values():
                            if any(c.chunk_id == chunk_id for c in kg.chunks):
                                similar_docs.add(kg.document_id)
                                break
                    
                    if entity_docs.intersection(similar_docs) == set():
                        # Different documents
                        cross_rel = CrossDocumentRelationship(
                            id=f"cross_{uuid.uuid4().hex[:8]}",
                            source_document_id=knowledge_graph.document_id,
                            target_document_id=list(similar_docs)[0] if similar_docs else 'unknown',
                            source_entity_id=entity.id,
                            target_entity_id=similar_entity.id,
                            relationship_type='same_entity' if entity.name.lower() == similar_entity.name.lower() else 'similar_entity',
                            confidence=0.8 if entity.name.lower() == similar_entity.name.lower() else 0.6,
                            evidence_chunks=entity.source_chunks + similar_entity.source_chunks
                        )
                        new_relationships.append(cross_rel)
        
        self.cross_document_relationships.extend(new_relationships)
        logger.info(f"Discovered {len(new_relationships)} cross-document relationships")
    
    async def _find_similar_entities(self, entity: Entity) -> List[Entity]:
        """Find similar entities across all documents."""
        similar_entities = []
        
        for other_entity in self.global_entities.values():
            if other_entity.id == entity.id:
                continue
            
            # Name similarity
            name_similarity = self._calculate_text_similarity(entity.name, other_entity.name)
            
            # Type must match
            if entity.type == other_entity.type and name_similarity > self.similarity_threshold:
                similar_entities.append(other_entity)
        
        return similar_entities
    
    def _calculate_text_similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity between two text strings."""
        # Simple Jaccard similarity
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        if not union:
            return 0.0
        
        return len(intersection) / len(union)
    
    async def _store_knowledge_graph_ipld(self, knowledge_graph: KnowledgeGraph) -> str:
        """Store knowledge graph in IPLD format."""
        # Convert to serializable format
        kg_data = {
            'graph_id': knowledge_graph.graph_id,
            'document_id': knowledge_graph.document_id,
            'entities': [asdict(entity) for entity in knowledge_graph.entities],
            'relationships': [asdict(rel) for rel in knowledge_graph.relationships],
            'chunks': [asdict(chunk) for chunk in knowledge_graph.chunks],
            'metadata': knowledge_graph.metadata,
            'creation_timestamp': knowledge_graph.creation_timestamp
        }
        
        # Remove numpy arrays from entities for JSON serialization
        for entity_data in kg_data['entities']:
            if 'embedding' in entity_data and entity_data['embedding'] is not None:
                entity_data['embedding'] = entity_data['embedding'].tolist()
        
        # Remove numpy arrays from chunks
        for chunk_data in kg_data['chunks']:
            if 'embedding' in chunk_data and chunk_data['embedding'] is not None:
                chunk_data['embedding'] = chunk_data['embedding'].tolist()
        
        try:
            # Store in IPLD
            cid = await self.storage.store_json(kg_data)
            logger.info(f"Stored knowledge graph in IPLD: {cid}")
            return cid
        except Exception as e:
            logger.error(f"Failed to store knowledge graph in IPLD: {e}")
            return ""
    
    async def query_graph(self, 
                         query: str, 
                         graph_id: Optional[str] = None,
                         max_results: int = 10) -> Dict[str, Any]:
        """
        Query the knowledge graph for information.
        
        Args:
            query: Natural language query
            graph_id: Specific graph to query (None for global)
            max_results: Maximum number of results
            
        Returns:
            Query results with entities, relationships, and context
        """
        if graph_id and graph_id in self.knowledge_graphs:
            kg = self.knowledge_graphs[graph_id]
            entities = kg.entities
            relationships = kg.relationships
        else:
            # Query global graph
            entities = list(self.global_entities.values())
            relationships = []
            for kg in self.knowledge_graphs.values():
                relationships.extend(kg.relationships)
        
        # Simple keyword-based search (can be enhanced with semantic search)
        query_lower = query.lower()
        matching_entities = []
        
        for entity in entities:
            score = 0
            
            # Name match
            if query_lower in entity.name.lower():
                score += 2
            
            # Type match
            if query_lower in entity.type.lower():
                score += 1
            
            # Description match
            if query_lower in entity.description.lower():
                score += 1
            
            if score > 0:
                matching_entities.append((entity, score))
        
        # Sort by score and limit results
        matching_entities.sort(key=lambda x: x[1], reverse=True)
        top_entities = [entity for entity, score in matching_entities[:max_results]]
        
        # Find related relationships
        entity_ids = {entity.id for entity in top_entities}
        related_relationships = [
            rel for rel in relationships
            if rel.source_entity_id in entity_ids or rel.target_entity_id in entity_ids
        ]
        
        return {
            'query': query,
            'entities': [asdict(entity) for entity in top_entities],
            'relationships': [asdict(rel) for rel in related_relationships],
            'total_matches': len(matching_entities),
            'timestamp': datetime.utcnow().isoformat()
        }
    
    async def get_entity_neighborhood(self, 
                                    entity_id: str, 
                                    depth: int = 2) -> Dict[str, Any]:
        """Get the neighborhood of an entity in the graph."""
        if entity_id not in self.global_entities:
            return {'error': 'Entity not found'}
        
        # Use global graph for neighborhood analysis
        if entity_id not in self.global_graph:
            return {'error': 'Entity not in graph'}
        
        # Get subgraph within specified depth
        subgraph_nodes = set([entity_id])
        
        for d in range(depth):
            new_nodes = set()
            for node in subgraph_nodes:
                # Add neighbors
                new_nodes.update(self.global_graph.neighbors(node))
                new_nodes.update(self.global_graph.predecessors(node))
            subgraph_nodes.update(new_nodes)
        
        # Extract subgraph
        subgraph = self.global_graph.subgraph(subgraph_nodes)
        
        # Convert to serializable format
        nodes_data = []
        for node in subgraph.nodes():
            node_data = dict(subgraph.nodes[node])
            node_data['id'] = node
            nodes_data.append(node_data)
        
        edges_data = []
        for source, target in subgraph.edges():
            edge_data = dict(subgraph.edges[source, target])
            edge_data['source'] = source
            edge_data['target'] = target
            edges_data.append(edge_data)
        
        return {
            'center_entity_id': entity_id,
            'depth': depth,
            'nodes': nodes_data,
            'edges': edges_data,
            'node_count': len(nodes_data),
            'edge_count': len(edges_data)
        }

import re
from contextlib import nullcontext
