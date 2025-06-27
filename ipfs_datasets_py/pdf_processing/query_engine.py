"""
Query Engine for PDF Processing Pipeline

Provides advanced querying capabilities over processed PDF content:
- Natural language querying over GraphRAG structures
- Semantic search across document collections
- Cross-document relationship analysis
- Multi-modal content retrieval
- IPLD-native query processing
"""

import asyncio
import logging
import json
from typing import Dict, List, Any, Optional, Union, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
import re

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer

from ..ipld import IPLDStorage
from .llm_optimizer import LLMDocument, LLMChunk
from .graphrag_integrator import GraphRAGIntegrator, KnowledgeGraph, Entity, Relationship

logger = logging.getLogger(__name__)

@dataclass
class QueryResult:
    """Single query result item."""
    id: str
    type: str  # 'entity', 'relationship', 'chunk', 'document'
    content: str
    relevance_score: float
    source_document: str
    source_chunks: List[str]
    metadata: Dict[str, Any]

@dataclass
class QueryResponse:
    """Complete query response."""
    query: str
    query_type: str
    results: List[QueryResult]
    total_results: int
    processing_time: float
    suggestions: List[str]
    metadata: Dict[str, Any]

@dataclass
class SemanticSearchResult:
    """Result from semantic search."""
    chunk_id: str
    content: str
    similarity_score: float
    document_id: str
    page_number: int
    semantic_type: str
    related_entities: List[str]

class QueryEngine:
    """
    Advanced query engine for PDF knowledge base.
    """
    
    def __init__(self, 
                 graphrag_integrator: GraphRAGIntegrator,
                 storage: Optional[IPLDStorage] = None,
                 embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"):
        """
        Initialize the query engine.
        
        Args:
            graphrag_integrator: GraphRAG integration system
            storage: IPLD storage instance
            embedding_model: Model for semantic search
        """
        self.graphrag = graphrag_integrator
        self.storage = storage or IPLDStorage()
        
        # Initialize embedding model for semantic search
        try:
            self.embedding_model = SentenceTransformer(embedding_model)
            logger.info(f"Loaded embedding model: {embedding_model}")
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            self.embedding_model = None
        
        # Query processing components
        self.query_processors = {
            'entity_search': self._process_entity_query,
            'relationship_search': self._process_relationship_query,
            'semantic_search': self._process_semantic_query,
            'document_search': self._process_document_query,
            'cross_document': self._process_cross_document_query,
            'graph_traversal': self._process_graph_traversal_query
        }
        
        # Cache for embeddings and frequent queries
        self.embedding_cache = {}
        self.query_cache = {}
        
    async def query(self, 
                   query_text: str,
                   query_type: Optional[str] = None,
                   filters: Optional[Dict[str, Any]] = None,
                   max_results: int = 20) -> QueryResponse:
        """
        Process a natural language query.
        
        Args:
            query_text: Natural language query
            query_type: Specific query type or auto-detect
            filters: Additional filters (document_id, entity_type, etc.)
            max_results: Maximum number of results
            
        Returns:
            QueryResponse with results and metadata
        """
        start_time = asyncio.get_event_loop().time()
        
        # Normalize query
        normalized_query = self._normalize_query(query_text)
        
        # Auto-detect query type if not specified
        if not query_type:
            query_type = self._detect_query_type(normalized_query)
        
        logger.info(f"Processing {query_type} query: {normalized_query}")
        
        # Check cache
        cache_key = f"{query_type}:{normalized_query}:{json.dumps(filters, sort_keys=True)}"
        if cache_key in self.query_cache:
            cached_result = self.query_cache[cache_key]
            logger.info("Returning cached query result")
            return cached_result
        
        # Process query based on type
        if query_type in self.query_processors:
            results = await self.query_processors[query_type](
                normalized_query, filters, max_results
            )
        else:
            # Fallback to semantic search
            results = await self._process_semantic_query(
                normalized_query, filters, max_results
            )
        
        # Generate suggestions
        suggestions = await self._generate_query_suggestions(normalized_query, results)
        
        processing_time = asyncio.get_event_loop().time() - start_time
        
        # Build response
        response = QueryResponse(
            query=query_text,
            query_type=query_type,
            results=results,
            total_results=len(results),
            processing_time=processing_time,
            suggestions=suggestions,
            metadata={
                'normalized_query': normalized_query,
                'filters_applied': filters or {},
                'timestamp': datetime.utcnow().isoformat()
            }
        )
        
        # Cache response
        self.query_cache[cache_key] = response
        
        logger.info(f"Query processed in {processing_time:.2f}s, {len(results)} results")
        return response
    
    def _normalize_query(self, query: str) -> str:
        """Normalize query text for processing."""
        # Convert to lowercase
        normalized = query.lower().strip()
        
        # Remove extra whitespace
        normalized = re.sub(r'\s+', ' ', normalized)
        
        # Remove common stop words for better matching
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
        words = normalized.split()
        filtered_words = [word for word in words if word not in stop_words]
        
        return ' '.join(filtered_words)
    
    def _detect_query_type(self, query: str) -> str:
        """Auto-detect query type based on query patterns."""
        query_lower = query.lower()
        
        # Entity search patterns
        if any(keyword in query_lower for keyword in ['who is', 'what is', 'person', 'organization', 'company']):
            return 'entity_search'
        
        # Relationship patterns
        if any(keyword in query_lower for keyword in ['relationship', 'related', 'connected', 'works for', 'founded']):
            return 'relationship_search'
        
        # Cross-document patterns
        if any(keyword in query_lower for keyword in ['across documents', 'compare', 'different documents', 'multiple']):
            return 'cross_document'
        
        # Graph traversal patterns
        if any(keyword in query_lower for keyword in ['path', 'connected through', 'how are', 'degree']):
            return 'graph_traversal'
        
        # Document search patterns
        if any(keyword in query_lower for keyword in ['document', 'paper', 'article', 'file']):
            return 'document_search'
        
        # Default to semantic search
        return 'semantic_search'
    
    async def _process_entity_query(self, 
                                   query: str, 
                                   filters: Optional[Dict[str, Any]], 
                                   max_results: int) -> List[QueryResult]:
        """Process entity-focused queries."""
        results = []
        
        # Get all entities from GraphRAG
        all_entities = list(self.graphrag.global_entities.values())
        
        # Apply filters
        if filters:
            if 'entity_type' in filters:
                all_entities = [e for e in all_entities if e.type == filters['entity_type']]
            if 'document_id' in filters:
                # Filter by document (check if entity appears in document chunks)
                doc_entities = []
                for entity in all_entities:
                    for kg in self.graphrag.knowledge_graphs.values():
                        if kg.document_id == filters['document_id']:
                            if any(chunk.chunk_id in entity.source_chunks for chunk in kg.chunks):
                                doc_entities.append(entity)
                                break
                all_entities = doc_entities
        
        # Score entities by query relevance
        scored_entities = []
        query_words = set(query.split())
        
        for entity in all_entities:
            score = 0
            entity_words = set(entity.name.lower().split())
            entity_desc_words = set(entity.description.lower().split())
            
            # Name similarity
            name_overlap = len(query_words.intersection(entity_words))
            score += name_overlap * 2
            
            # Description similarity
            desc_overlap = len(query_words.intersection(entity_desc_words))
            score += desc_overlap
            
            # Exact name match bonus
            if any(word in entity.name.lower() for word in query_words):
                score += 3
            
            # Type match
            if entity.type in query:
                score += 1
            
            if score > 0:
                scored_entities.append((entity, score))
        
        # Sort and limit results
        scored_entities.sort(key=lambda x: x[1], reverse=True)
        
        for entity, score in scored_entities[:max_results]:
            result = QueryResult(
                id=entity.id,
                type='entity',
                content=f"{entity.name} ({entity.type}): {entity.description}",
                relevance_score=score / 10.0,  # Normalize score
                source_document='multiple' if len(set(self._get_entity_documents(entity))) > 1 else self._get_entity_documents(entity)[0],
                source_chunks=entity.source_chunks,
                metadata={
                    'entity_name': entity.name,
                    'entity_type': entity.type,
                    'confidence': entity.confidence,
                    'properties': entity.properties
                }
            )
            results.append(result)
        
        return results
    
    async def _process_relationship_query(self, 
                                        query: str, 
                                        filters: Optional[Dict[str, Any]], 
                                        max_results: int) -> List[QueryResult]:
        """Process relationship-focused queries."""
        results = []
        
        # Get all relationships from all knowledge graphs
        all_relationships = []
        for kg in self.graphrag.knowledge_graphs.values():
            all_relationships.extend(kg.relationships)
        
        # Apply filters
        if filters:
            if 'relationship_type' in filters:
                all_relationships = [r for r in all_relationships if r.relationship_type == filters['relationship_type']]
            if 'entity_id' in filters:
                all_relationships = [
                    r for r in all_relationships 
                    if r.source_entity_id == filters['entity_id'] or r.target_entity_id == filters['entity_id']
                ]
        
        # Score relationships by query relevance
        scored_relationships = []
        query_words = set(query.split())
        
        for relationship in all_relationships:
            score = 0
            
            # Get entity names for context
            source_entity = self.graphrag.global_entities.get(relationship.source_entity_id)
            target_entity = self.graphrag.global_entities.get(relationship.target_entity_id)
            
            if not source_entity or not target_entity:
                continue
            
            # Relationship type match
            rel_type_words = set(relationship.relationship_type.replace('_', ' ').split())
            type_overlap = len(query_words.intersection(rel_type_words))
            score += type_overlap * 2
            
            # Entity name matches
            source_words = set(source_entity.name.lower().split())
            target_words = set(target_entity.name.lower().split())
            
            source_overlap = len(query_words.intersection(source_words))
            target_overlap = len(query_words.intersection(target_words))
            score += source_overlap + target_overlap
            
            # Description match
            desc_words = set(relationship.description.lower().split())
            desc_overlap = len(query_words.intersection(desc_words))
            score += desc_overlap
            
            if score > 0:
                scored_relationships.append((relationship, score, source_entity, target_entity))
        
        # Sort and limit results
        scored_relationships.sort(key=lambda x: x[1], reverse=True)
        
        for relationship, score, source_entity, target_entity in scored_relationships[:max_results]:
            result = QueryResult(
                id=relationship.id,
                type='relationship',
                content=f"{source_entity.name} {relationship.relationship_type.replace('_', ' ')} {target_entity.name}",
                relevance_score=score / 10.0,
                source_document=self._get_relationship_documents(relationship)[0] if self._get_relationship_documents(relationship) else 'unknown',
                source_chunks=relationship.source_chunks,
                metadata={
                    'relationship_type': relationship.relationship_type,
                    'source_entity': {
                        'id': source_entity.id,
                        'name': source_entity.name,
                        'type': source_entity.type
                    },
                    'target_entity': {
                        'id': target_entity.id,
                        'name': target_entity.name,
                        'type': target_entity.type
                    },
                    'confidence': relationship.confidence,
                    'properties': relationship.properties
                }
            )
            results.append(result)
        
        return results
    
    async def _process_semantic_query(self, 
                                    query: str, 
                                    filters: Optional[Dict[str, Any]], 
                                    max_results: int) -> List[QueryResult]:
        """Process semantic search queries."""
        if not self.embedding_model:
            logger.warning("No embedding model available for semantic search")
            return []
        
        results = []
        
        # Generate query embedding
        query_embedding = self.embedding_model.encode([query])[0]
        
        # Get all chunks from all documents
        all_chunks = []
        for kg in self.graphrag.knowledge_graphs.values():
            for chunk in kg.chunks:
                if chunk.embedding is not None:
                    all_chunks.append((chunk, kg.document_id))
        
        if not all_chunks:
            logger.warning("No chunks with embeddings found for semantic search")
            return []
        
        # Calculate similarities
        chunk_similarities = []
        for chunk, doc_id in all_chunks:
            if chunk.embedding is not None:
                similarity = cosine_similarity(
                    query_embedding.reshape(1, -1),
                    chunk.embedding.reshape(1, -1)
                )[0][0]
                chunk_similarities.append((chunk, doc_id, similarity))
        
        # Apply filters
        if filters:
            if 'document_id' in filters:
                chunk_similarities = [(c, d, s) for c, d, s in chunk_similarities if d == filters['document_id']]
            if 'semantic_type' in filters:
                chunk_similarities = [(c, d, s) for c, d, s in chunk_similarities if c.semantic_type == filters['semantic_type']]
            if 'min_similarity' in filters:
                chunk_similarities = [(c, d, s) for c, d, s in chunk_similarities if s >= filters['min_similarity']]
        
        # Sort by similarity and limit results
        chunk_similarities.sort(key=lambda x: x[2], reverse=True)
        
        for chunk, doc_id, similarity in chunk_similarities[:max_results]:
            # Find related entities
            related_entities = []
            for entity in self.graphrag.global_entities.values():
                if chunk.chunk_id in entity.source_chunks:
                    related_entities.append(entity.name)
            
            result = QueryResult(
                id=chunk.chunk_id,
                type='chunk',
                content=chunk.content[:500] + '...' if len(chunk.content) > 500 else chunk.content,
                relevance_score=similarity,
                source_document=doc_id,
                source_chunks=[chunk.chunk_id],
                metadata={
                    'semantic_type': chunk.semantic_type,
                    'source_page': chunk.source_page,
                    'token_count': chunk.token_count,
                    'related_entities': related_entities,
                    'relationships': chunk.relationships
                }
            )
            results.append(result)
        
        return results
    
    async def _process_document_query(self, 
                                    query: str, 
                                    filters: Optional[Dict[str, Any]], 
                                    max_results: int) -> List[QueryResult]:
        """Process document-level queries."""
        results = []
        
        # Get all knowledge graphs (documents)
        all_documents = list(self.graphrag.knowledge_graphs.values())
        
        # Apply filters
        if filters:
            if 'document_id' in filters:
                all_documents = [kg for kg in all_documents if kg.document_id == filters['document_id']]
        
        # Score documents by query relevance
        scored_documents = []
        query_words = set(query.split())
        
        for kg in all_documents:
            score = 0
            
            # Title match
            title_words = set(kg.metadata.get('document_title', '').lower().split())
            title_overlap = len(query_words.intersection(title_words))
            score += title_overlap * 3
            
            # Entity matches
            entity_matches = 0
            for entity in kg.entities:
                entity_words = set(entity.name.lower().split())
                if query_words.intersection(entity_words):
                    entity_matches += 1
            score += entity_matches
            
            # Content matches (sample chunks)
            content_matches = 0
            for chunk in kg.chunks[:10]:  # Sample first 10 chunks
                chunk_words = set(chunk.content.lower().split())
                content_overlap = len(query_words.intersection(chunk_words))
                content_matches += content_overlap
            score += content_matches * 0.1
            
            if score > 0:
                scored_documents.append((kg, score))
        
        # Sort and limit results
        scored_documents.sort(key=lambda x: x[1], reverse=True)
        
        for kg, score in scored_documents[:max_results]:
            # Create document summary
            summary = f"Document: {kg.metadata.get('document_title', kg.document_id)}\n"
            summary += f"Entities: {len(kg.entities)}, Relationships: {len(kg.relationships)}, Chunks: {len(kg.chunks)}\n"
            summary += f"Key entities: {', '.join([e.name for e in kg.entities[:5]])}"
            
            result = QueryResult(
                id=kg.document_id,
                type='document',
                content=summary,
                relevance_score=score / 20.0,  # Normalize score
                source_document=kg.document_id,
                source_chunks=[chunk.chunk_id for chunk in kg.chunks],
                metadata={
                    'graph_id': kg.graph_id,
                    'title': kg.metadata.get('document_title', ''),
                    'entity_count': len(kg.entities),
                    'relationship_count': len(kg.relationships),
                    'chunk_count': len(kg.chunks),
                    'creation_timestamp': kg.creation_timestamp,
                    'ipld_cid': kg.ipld_cid
                }
            )
            results.append(result)
        
        return results
    
    async def _process_cross_document_query(self, 
                                          query: str, 
                                          filters: Optional[Dict[str, Any]], 
                                          max_results: int) -> List[QueryResult]:
        """Process cross-document analysis queries."""
        results = []
        
        # Get cross-document relationships
        cross_relationships = self.graphrag.cross_document_relationships
        
        if not cross_relationships:
            logger.info("No cross-document relationships found")
            return results
        
        # Score cross-document relationships
        scored_relationships = []
        query_words = set(query.split())
        
        for cross_rel in cross_relationships:
            score = 0
            
            # Get entities
            source_entity = self.graphrag.global_entities.get(cross_rel.source_entity_id)
            target_entity = self.graphrag.global_entities.get(cross_rel.target_entity_id)
            
            if not source_entity or not target_entity:
                continue
            
            # Entity name matches
            source_words = set(source_entity.name.lower().split())
            target_words = set(target_entity.name.lower().split())
            
            source_overlap = len(query_words.intersection(source_words))
            target_overlap = len(query_words.intersection(target_words))
            score += source_overlap + target_overlap
            
            # Relationship type match
            rel_type_words = set(cross_rel.relationship_type.replace('_', ' ').split())
            type_overlap = len(query_words.intersection(rel_type_words))
            score += type_overlap * 2
            
            if score > 0:
                scored_relationships.append((cross_rel, score, source_entity, target_entity))
        
        # Sort and limit results
        scored_relationships.sort(key=lambda x: x[1], reverse=True)
        
        for cross_rel, score, source_entity, target_entity in scored_relationships[:max_results]:
            content = f"Cross-document: {source_entity.name} ({cross_rel.source_document_id}) "
            content += f"{cross_rel.relationship_type.replace('_', ' ')} "
            content += f"{target_entity.name} ({cross_rel.target_document_id})"
            
            result = QueryResult(
                id=cross_rel.id,
                type='cross_document_relationship',
                content=content,
                relevance_score=score / 10.0,
                source_document=f"{cross_rel.source_document_id}, {cross_rel.target_document_id}",
                source_chunks=cross_rel.evidence_chunks,
                metadata={
                    'relationship_type': cross_rel.relationship_type,
                    'source_document': cross_rel.source_document_id,
                    'target_document': cross_rel.target_document_id,
                    'source_entity': {
                        'id': source_entity.id,
                        'name': source_entity.name,
                        'type': source_entity.type
                    },
                    'target_entity': {
                        'id': target_entity.id,
                        'name': target_entity.name,
                        'type': target_entity.type
                    },
                    'confidence': cross_rel.confidence
                }
            )
            results.append(result)
        
        return results
    
    async def _process_graph_traversal_query(self, 
                                           query: str, 
                                           filters: Optional[Dict[str, Any]], 
                                           max_results: int) -> List[QueryResult]:
        """Process graph traversal queries (paths, connections, etc.)."""
        results = []
        
        # Extract entity names from query for path finding
        entity_names = self._extract_entity_names_from_query(query)
        
        if len(entity_names) < 2:
            logger.info("Need at least 2 entities for graph traversal")
            return results
        
        # Find entities in graph
        start_entities = []
        end_entities = []
        
        for entity in self.graphrag.global_entities.values():
            for name in entity_names[:len(entity_names)//2]:
                if name.lower() in entity.name.lower():
                    start_entities.append(entity)
                    break
            
            for name in entity_names[len(entity_names)//2:]:
                if name.lower() in entity.name.lower():
                    end_entities.append(entity)
                    break
        
        if not start_entities or not end_entities:
            logger.info("Could not find entities for graph traversal")
            return results
        
        # Find paths between entities
        import networkx as nx
        
        for start_entity in start_entities[:3]:  # Limit to first 3
            for end_entity in end_entities[:3]:
                if start_entity.id == end_entity.id:
                    continue
                
                try:
                    # Find shortest path
                    path = nx.shortest_path(
                        self.graphrag.global_graph,
                        source=start_entity.id,
                        target=end_entity.id
                    )
                    
                    if len(path) > 1:
                        # Create path description
                        path_entities = []
                        for entity_id in path:
                            entity = self.graphrag.global_entities.get(entity_id)
                            if entity:
                                path_entities.append(entity.name)
                        
                        path_description = " → ".join(path_entities)
                        
                        # Calculate path relevance
                        relevance = 1.0 / len(path)  # Shorter paths are more relevant
                        
                        result = QueryResult(
                            id=f"path_{start_entity.id}_{end_entity.id}",
                            type='graph_path',
                            content=f"Path: {path_description}",
                            relevance_score=relevance,
                            source_document='multiple',
                            source_chunks=[],  # Paths don't have specific chunks
                            metadata={
                                'path_length': len(path),
                                'path_entities': path,
                                'start_entity': start_entity.name,
                                'end_entity': end_entity.name
                            }
                        )
                        results.append(result)
                
                except nx.NetworkXNoPath:
                    # No path found
                    continue
                except Exception as e:
                    logger.warning(f"Error finding path: {e}")
                    continue
        
        # Sort by relevance (path length)
        results.sort(key=lambda x: x.relevance_score, reverse=True)
        
        return results[:max_results]
    
    def _extract_entity_names_from_query(self, query: str) -> List[str]:
        """Extract potential entity names from query text."""
        # Simple approach: look for capitalized words/phrases
        words = query.split()
        entity_names = []
        
        current_name = []
        for word in words:
            if word[0].isupper() and len(word) > 2:
                current_name.append(word)
            else:
                if current_name:
                    entity_names.append(' '.join(current_name))
                    current_name = []
        
        # Add final name if exists
        if current_name:
            entity_names.append(' '.join(current_name))
        
        return entity_names
    
    def _get_entity_documents(self, entity: Entity) -> List[str]:
        """Get document IDs where entity appears."""
        documents = []
        for kg in self.graphrag.knowledge_graphs.values():
            if any(chunk.chunk_id in entity.source_chunks for chunk in kg.chunks):
                documents.append(kg.document_id)
        return documents if documents else ['unknown']
    
    def _get_relationship_documents(self, relationship: Relationship) -> List[str]:
        """Get document IDs where relationship appears."""
        documents = []
        for kg in self.graphrag.knowledge_graphs.values():
            if any(chunk.chunk_id in relationship.source_chunks for chunk in kg.chunks):
                documents.append(kg.document_id)
        return documents if documents else ['unknown']
    
    async def _generate_query_suggestions(self, 
                                        query: str, 
                                        results: List[QueryResult]) -> List[str]:
        """Generate query suggestions based on results."""
        suggestions = []
        
        # Entity-based suggestions
        entities_mentioned = set()
        for result in results[:5]:  # Top 5 results
            if 'entity_name' in result.metadata:
                entities_mentioned.add(result.metadata['entity_name'])
            if 'source_entity' in result.metadata:
                entities_mentioned.add(result.metadata['source_entity']['name'])
            if 'target_entity' in result.metadata:
                entities_mentioned.add(result.metadata['target_entity']['name'])
        
        # Suggest related entity queries
        for entity in list(entities_mentioned)[:3]:
            suggestions.append(f"What is {entity}?")
            suggestions.append(f"What are the relationships of {entity}?")
        
        # Document-based suggestions
        documents_mentioned = set()
        for result in results[:5]:
            if result.source_document != 'multiple' and result.source_document != 'unknown':
                documents_mentioned.add(result.source_document)
        
        if len(documents_mentioned) > 1:
            suggestions.append("Compare these documents")
            suggestions.append("Find cross-document relationships")
        
        # Type-based suggestions
        types_mentioned = set()
        for result in results[:5]:
            if 'relationship_type' in result.metadata:
                types_mentioned.add(result.metadata['relationship_type'])
        
        for rel_type in list(types_mentioned)[:2]:
            suggestions.append(f"Find all {rel_type.replace('_', ' ')} relationships")
        
        return suggestions[:5]  # Limit to 5 suggestions
    
    async def get_query_analytics(self) -> Dict[str, Any]:
        """Get analytics about query patterns and performance."""
        if not self.query_cache:
            return {'message': 'No query data available'}
        
        # Analyze query patterns
        query_types = {}
        total_processing_time = 0
        result_counts = []
        
        for cached_response in self.query_cache.values():
            query_type = cached_response.query_type
            query_types[query_type] = query_types.get(query_type, 0) + 1
            total_processing_time += cached_response.processing_time
            result_counts.append(cached_response.total_results)
        
        avg_processing_time = total_processing_time / len(self.query_cache)
        avg_results = sum(result_counts) / len(result_counts) if result_counts else 0
        
        return {
            'total_queries': len(self.query_cache),
            'query_types': query_types,
            'average_processing_time': avg_processing_time,
            'average_results_per_query': avg_results,
            'cache_size': len(self.query_cache),
            'embedding_cache_size': len(self.embedding_cache)
        }
