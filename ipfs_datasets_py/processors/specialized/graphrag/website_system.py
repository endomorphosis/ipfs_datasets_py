"""
Website GraphRAG System

Complete GraphRAG system optimized for website content processing.
Provides hierarchical search, multi-modal capabilities, and cross-reference analysis.

Features:
- Hierarchical search (page → section → paragraph)
- Multi-modal search (text, audio, video, images) 
- Temporal search (content across different archive dates)
- Cross-reference search (links between pages)
- Semantic clustering of related content
"""

import json
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass, field

import numpy as np

# Import existing components
from ipfs_datasets_py.content_discovery import ContentManifest
from ipfs_datasets_py.processors.multimodal_processor import ProcessedContentBatch, ProcessedContent
from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import KnowledgeGraph, Entity, Relationship
from ipfs_datasets_py.processors.specialized.graphrag.integration import GraphRAGIntegration

# Set up logging
logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Individual search result from website content"""
    source_url: str
    content_type: str  # 'html', 'pdf', 'audio', 'video', 'image'
    title: str
    content_snippet: str
    relevance_score: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    related_entities: List[str] = field(default_factory=list)
    cross_references: List[str] = field(default_factory=list)


@dataclass
class WebsiteGraphRAGResult:
    """Comprehensive search result from GraphRAG website system"""
    query: str
    results: List[SearchResult]
    website_url: str
    total_results: int
    search_metadata: Dict[str, Any]
    reasoning_trace: Optional[str] = None
    knowledge_graph_connections: List[Dict[str, Any]] = field(default_factory=list)
    processing_time_seconds: float = 0.0

    def __await__(self):
        async def _wrap():
            return self

        return _wrap().__await__()


class AwaitableList(list):
    """List wrapper that can be awaited to return itself."""

    def __await__(self):
        async def _wrap():
            return self

        return _wrap().__await__()
    
    @property
    def content_type_breakdown(self) -> Dict[str, int]:
        """Breakdown of results by content type"""
        breakdown = {}
        for result in self.results:
            content_type = result.content_type
            breakdown[content_type] = breakdown.get(content_type, 0) + 1
        return breakdown


class WebsiteGraphRAGSystem:
    """
    Complete GraphRAG system for website content processing.
    
    Features:
    - Hierarchical search (page → section → paragraph)
    - Multi-modal search (text, audio, video, images)
    - Temporal search (content across different archive dates)
    - Cross-reference search (links between pages)
    - Semantic clustering of related content
    
    Usage:
        system = WebsiteGraphRAGSystem(
            url="https://example.com",
            content_manifest=manifest,
            processed_content=content,
            knowledge_graph=graph,
            graphrag=graphrag_instance
        )
        
        results = system.query("What is this website about?")
    """
    
    def __init__(
        self,
        url: Optional[str] = None,
        content_manifest: Optional[ContentManifest] = None,
        processed_content: Optional[ProcessedContentBatch] = None,
        knowledge_graph: Optional[Union[KnowledgeGraph, Dict[str, Any]]] = None,
        graphrag: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None,
        # Support direct testing parameters
        embeddings: Optional[Dict[str, List[float]]] = None,
        documents: Optional[Dict[str, Dict[str, Any]]] = None
    ):
        """
        Initialize website GraphRAG system
        
        Args:
            url: Website URL
            content_manifest: Discovered content manifest
            processed_content: Processed content batch  
            knowledge_graph: Extracted knowledge graph (KnowledgeGraph object or dict)
            graphrag: GraphRAG integration instance
            metadata: Additional metadata
            embeddings: Direct embeddings dict for testing
            documents: Direct documents dict for testing
        """
        self.url = url or "test://example.com"
        self.content_manifest = content_manifest
        self.processed_content = processed_content
        
        # Handle knowledge graph as dict or object
        if isinstance(knowledge_graph, dict):
            # Convert dict to KnowledgeGraph object
            self.knowledge_graph = KnowledgeGraph()
            if "entities" in knowledge_graph:
                for entity_data in knowledge_graph["entities"]:
                    if isinstance(entity_data, dict):
                        entity = Entity(
                            entity_id=entity_data.get("id", str(uuid.uuid4())),
                            entity_type=entity_data.get("type", "UNKNOWN"),
                            name=entity_data.get("name", "Unknown"),
                            confidence=entity_data.get("confidence", 1.0)
                        )
                        self.knowledge_graph.add_entity(entity)
        else:
            self.knowledge_graph = knowledge_graph
            
        self.graphrag = graphrag
        self.metadata = metadata or {}
        
        # Handle direct test parameters
        if embeddings:
            self.embeddings = embeddings
        if documents:
            self.documents = documents
        
        # Initialize search capabilities
        self._initialize_search_indexes()
        
        logger.info(f"WebsiteGraphRAGSystem initialized for {url}")
    
    def _initialize_search_indexes(self):
        """Initialize search indexes for different content types"""
        try:
            # Create content type indexes
            self._content_by_type = {
                'html': [],
                'pdf': [],
                'audio': [],
                'video': [],
                'image': []
            }
            
            # Initialize empty indexes if no processed content
            if not self.processed_content or not hasattr(self.processed_content, 'processed_items'):
                self._content_by_url = {}
                self._text_items = []
                logger.info("No processed content available - initialized empty search indexes")
                return
            
            # Index content by type
            for item in self.processed_content.processed_items:
                content_type = item.content_type
                if content_type in self._content_by_type:
                    self._content_by_type[content_type].append(item)
            
            # Create URL index
            self._content_by_url = {
                item.source_url: item 
                for item in self.processed_content.processed_items
            }
            
            # Create text index for vector search
            self._text_items = [
                item for item in self.processed_content.processed_items
                if item.text_content and len(item.text_content.strip()) > 0
            ]
            
            logger.info(
                f"Search indexes initialized: {len(self._text_items)} text items, "
                f"{len(self._content_by_url)} total items"
            )
            
        except Exception as e:
            logger.error(f"Failed to initialize search indexes: {e}")
            # Initialize empty indexes to prevent further errors
            self._content_by_type = {'html': [], 'pdf': [], 'audio': [], 'video': [], 'image': []}
            self._content_by_url = {}
            self._text_items = []
    
    def query(
        self,
        query_text: str,
        content_types: Optional[List[str]] = None,
        temporal_scope: Optional[str] = None,
        reasoning_depth: str = "moderate",
        max_results: int = 10
    ) -> WebsiteGraphRAGResult:
        """
        Query website content using GraphRAG
        
        Args:
            query_text: Natural language query
            content_types: Filter by content types ['html', 'pdf', 'audio', 'video', 'image']
            temporal_scope: Filter by time range if multiple archives
            reasoning_depth: 'shallow', 'moderate', 'deep'
            max_results: Maximum number of results to return
        
        Returns:
            Comprehensive search results with reasoning traces
        """
        start_time = datetime.now()
        
        try:
            logger.info(f"Processing query: '{query_text}' with {reasoning_depth} reasoning")
            
            # Filter content by type if specified
            filtered_content = self._filter_content_by_types(content_types)
            
            # Perform GraphRAG search if available
            if self.graphrag:
                graphrag_results = self._perform_graphrag_search(
                    query_text, filtered_content, reasoning_depth, max_results
                )
            else:
                # Fallback to vector search only
                graphrag_results = self._perform_vector_search_fallback(
                    query_text, filtered_content, max_results
                )
            
            # Convert to SearchResult objects
            search_results = self._convert_to_search_results(graphrag_results)
            
            # Enhance with website-specific context
            enhanced_results = self._enhance_website_context(search_results)
            
            # Add knowledge graph connections
            kg_connections = self._find_knowledge_graph_connections(
                query_text, enhanced_results
            )
            
            processing_time = (datetime.now() - start_time).total_seconds()
            
            return WebsiteGraphRAGResult(
                query=query_text,
                results=enhanced_results[:max_results],
                website_url=self.url,
                total_results=len(enhanced_results),
                search_metadata=self._generate_search_metadata(
                    content_types, temporal_scope, reasoning_depth
                ),
                knowledge_graph_connections=kg_connections,
                processing_time_seconds=processing_time,
                reasoning_trace=getattr(graphrag_results, 'reasoning_trace', None)
            )
            
        except Exception as e:
            logger.error(f"Query processing failed: {e}")
            # Return empty result on error
            return WebsiteGraphRAGResult(
                query=query_text,
                results=[],
                website_url=self.url,
                total_results=0,
                search_metadata={'error': str(e)},
                processing_time_seconds=(datetime.now() - start_time).total_seconds()
            )
    
    def _filter_content_by_types(
        self, 
        content_types: Optional[List[str]]
    ) -> List[ProcessedContent]:
        """Filter content by specified types"""
        if not content_types:
            return self._text_items
        
        filtered_items = []
        for content_type in content_types:
            if content_type in self._content_by_type:
                filtered_items.extend(self._content_by_type[content_type])
        
        return filtered_items
    
    def _perform_graphrag_search(
        self,
        query_text: str,
        filtered_content: List[ProcessedContent],
        reasoning_depth: str,
        max_results: int
    ) -> Any:
        """Perform GraphRAG search using integrated system"""
        try:
            # Use GraphRAG query engine
            graphrag_result = self.graphrag.query(
                query_text=query_text,
                top_k=max_results,
                include_cross_document_reasoning=True,
                reasoning_depth=reasoning_depth,
                content_filter=[item.source_url for item in filtered_content]
            )
            
            return graphrag_result
            
        except Exception as e:
            logger.warning(f"GraphRAG search failed, falling back to vector search: {e}")
            return self._perform_vector_search_fallback(query_text, filtered_content, max_results)
    
    def _perform_vector_search_fallback(
        self,
        query_text: str,
        filtered_content: List[ProcessedContent],
        max_results: int
    ) -> Dict[str, Any]:
        """Fallback vector search when GraphRAG is not available"""
        results = []
        
        try:
            # Simple text-based matching for fallback
            # In production, this would use actual vector similarity
            query_terms = query_text.lower().split()
            
            for item in filtered_content:
                if not item.text_content:
                    continue
                
                text_lower = item.text_content.lower()
                
                # Calculate simple relevance score based on term matches
                matches = sum(1 for term in query_terms if term in text_lower)
                relevance_score = matches / len(query_terms) if query_terms else 0
                
                if relevance_score > 0:
                    results.append({
                        'source_url': item.source_url,
                        'content_type': item.content_type,
                        'text_content': item.text_content,
                        'relevance_score': relevance_score,
                        'metadata': item.metadata
                    })
            
            # Sort by relevance score
            results.sort(key=lambda x: x['relevance_score'], reverse=True)
            
            return {
                'results': results[:max_results],
                'reasoning_trace': 'Used fallback vector search (simple text matching)',
                'method': 'vector_fallback'
            }
            
        except Exception as e:
            logger.error(f"Vector search fallback failed: {e}")
            return {'results': [], 'error': str(e)}
    
    def _convert_to_search_results(self, graphrag_results: Any) -> List[SearchResult]:
        """Convert GraphRAG results to SearchResult objects"""
        search_results = []
        
        try:
            # Handle different result formats
            if hasattr(graphrag_results, 'results'):
                results_list = graphrag_results.results
            elif isinstance(graphrag_results, dict) and 'results' in graphrag_results:
                results_list = graphrag_results['results']
            else:
                results_list = []
            
            for result in results_list:
                # Extract information from result
                if isinstance(result, dict):
                    source_url = result.get('source_url', '')
                    content_type = result.get('content_type', 'unknown')
                    text_content = result.get('text_content', '')
                    relevance_score = result.get('relevance_score', 0.0)
                    metadata = result.get('metadata', {})
                else:
                    # Handle other result formats
                    source_url = getattr(result, 'source_url', '')
                    content_type = getattr(result, 'content_type', 'unknown')
                    text_content = getattr(result, 'text_content', '')
                    relevance_score = getattr(result, 'relevance_score', 0.0)
                    metadata = getattr(result, 'metadata', {})
                
                # Generate title and snippet
                title = self._generate_title(source_url, content_type, metadata)
                snippet = self._generate_snippet(text_content)
                
                search_result = SearchResult(
                    source_url=source_url,
                    content_type=content_type,
                    title=title,
                    content_snippet=snippet,
                    relevance_score=relevance_score,
                    metadata=metadata
                )
                
                search_results.append(search_result)
                
        except Exception as e:
            logger.error(f"Failed to convert GraphRAG results: {e}")
        
        return search_results
    
    def _enhance_website_context(self, results: List[SearchResult]) -> List[SearchResult]:
        """Enhance results with website-specific context"""
        for result in results:
            try:
                # Add cross-references
                result.cross_references = self._find_cross_references(result.source_url)
                
                # Add related entities from knowledge graph
                if self.knowledge_graph:
                    result.related_entities = self._find_related_entities(
                        result.content_snippet
                    )
                
                # Enhance metadata with website context
                result.metadata['website_url'] = self.url
                result.metadata['content_manifest_stats'] = self.content_manifest.content_summary
                
            except Exception as e:
                logger.warning(f"Failed to enhance context for {result.source_url}: {e}")
        
        return results
    
    def _find_knowledge_graph_connections(
        self, 
        query_text: str, 
        results: List[SearchResult]
    ) -> List[Dict[str, Any]]:
        """Find connections in knowledge graph related to query and results"""
        if not self.knowledge_graph:
            return []
        
        connections = []
        
        try:
            # Find entities mentioned in query
            query_entities = self._extract_entities_from_text(query_text)
            
            # Find entities in result content
            result_entities = []
            for result in results:
                entities = self._extract_entities_from_text(result.content_snippet)
                result_entities.extend(entities)
            
            # Find relationships between query entities and result entities
            for query_entity in query_entities:
                for result_entity in result_entities:
                    relationship = self._find_relationship(query_entity, result_entity)
                    if relationship:
                        connections.append({
                            'query_entity': query_entity,
                            'result_entity': result_entity,
                            'relationship': relationship,
                            'confidence': 0.8  # Placeholder confidence
                        })
            
        except Exception as e:
            logger.warning(f"Failed to find knowledge graph connections: {e}")
        
        return connections
    
    def get_content_overview(self) -> Dict[str, Any]:
        """Get overview of all processed website content"""
        return {
            'base_url': self.url,
            'discovery_stats': self.content_manifest.content_summary,
            'processing_stats': self.processed_content.processing_stats,
            'total_text_items': len(self._text_items),
            'knowledge_graph_stats': {
                'entities': len(self.knowledge_graph.entities) if self.knowledge_graph else 0,
                'relationships': len(self.knowledge_graph.relationships) if self.knowledge_graph else 0
            },
            'graphrag_enabled': self.graphrag is not None,
            'processing_metadata': self.processed_content.batch_metadata
        }
    
    def search_by_content_type(
        self, 
        content_type: str, 
        query: Optional[str] = None
    ) -> List[ProcessedContent]:
        """Search within specific content type"""
        if content_type not in self._content_by_type:
            return []
        
        filtered_items = self._content_by_type[content_type]
        
        if not query:
            return filtered_items
        
        # Simple text filtering
        matching_items = []
        query_lower = query.lower()
        
        for item in filtered_items:
            if item.text_content and query_lower in item.text_content.lower():
                matching_items.append(item)
        
        return matching_items
    
    def get_related_content(
        self, 
        source_url: str, 
        max_related: int = 5
    ) -> List[ProcessedContent]:
        """Find content related to specific source URL using knowledge graph"""
        if source_url not in self._content_by_url:
            return AwaitableList()
        
        source_item = self._content_by_url[source_url]
        related_items = []
        
        try:
            # Find entities in source content
            source_entities = self._extract_entities_from_text(source_item.text_content)
            
            # Find other content with overlapping entities
            for item in self._text_items:
                if item.source_url == source_url:
                    continue
                
                item_entities = self._extract_entities_from_text(item.text_content)
                overlap = set(source_entities) & set(item_entities)
                
                if overlap:
                    # Calculate similarity based on entity overlap
                    similarity = len(overlap) / (len(source_entities) + len(item_entities) - len(overlap))
                    item.metadata['similarity_score'] = similarity
                    related_items.append(item)
            
            # Sort by similarity and return top results
            related_items.sort(key=lambda x: x.metadata.get('similarity_score', 0), reverse=True)
            return AwaitableList(related_items[:max_related])
            
        except Exception as e:
            logger.warning(f"Failed to find related content: {e}")
            return AwaitableList()
    
    def export_dataset(
        self, 
        output_format: str = "json",
        include_embeddings: bool = False
    ) -> str:
        """Export processed website content as dataset"""
        try:
            dataset = {
                'metadata': {
                    'website_url': self.url,
                    'export_timestamp': datetime.now().isoformat(),
                    'total_items': len(self.processed_content.processed_items),
                    'content_overview': self.get_content_overview()
                },
                'content': []
            }
            
            for item in self.processed_content.processed_items:
                item_data = {
                    'source_url': item.source_url,
                    'content_type': item.content_type,
                    'text_content': item.text_content,
                    'text_length': item.text_length,
                    'confidence_score': item.confidence_score,
                    'metadata': item.metadata,
                    'processing_timestamp': item.processing_timestamp.isoformat()
                }
                
                if include_embeddings and item.has_embeddings:
                    item_data['embeddings'] = item.embeddings.tolist()
                
                dataset['content'].append(item_data)
            
            # Export in requested format
            if output_format.lower() == 'json':
                output_file = f"{self.url.replace('://', '_').replace('/', '_')}_dataset.json"
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(dataset, f, indent=2, ensure_ascii=False)
                return output_file
            
            else:
                raise ValueError(f"Unsupported export format: {output_format}")
            
        except Exception as e:
            logger.error(f"Dataset export failed: {e}")
            raise
    
    # Helper methods
    
    def _generate_title(
        self, 
        source_url: str, 
        content_type: str, 
        metadata: Dict[str, Any]
    ) -> str:
        """Generate title for search result"""
        # Try to get title from metadata
        if 'title' in metadata:
            return metadata['title']
        
        # Generate from URL
        from urllib.parse import urlparse
        parsed = urlparse(source_url)
        filename = parsed.path.split('/')[-1] or parsed.netloc
        
        return f"{content_type.upper()}: {filename}"
    
    def _generate_snippet(self, text_content: str, max_length: int = 200) -> str:
        """Generate snippet from text content"""
        if not text_content:
            return ""
        
        # Clean up text
        cleaned = text_content.strip().replace('\n', ' ')
        
        # Truncate to max length
        if len(cleaned) <= max_length:
            return cleaned
        
        # Find a good break point (end of sentence or word)
        snippet = cleaned[:max_length]
        last_sentence = snippet.rfind('.')
        last_word = snippet.rfind(' ')
        
        if last_sentence > max_length * 0.7:  # If sentence end is not too early
            return snippet[:last_sentence + 1]
        elif last_word > 0:
            return snippet[:last_word] + "..."
        else:
            return snippet + "..."
    
    def _find_cross_references(self, source_url: str) -> List[str]:
        """Find cross-references to this URL from other content"""
        cross_refs = []
        
        for item in self._text_items:
            if item.source_url != source_url and source_url in item.text_content:
                cross_refs.append(item.source_url)
        
        return cross_refs
    
    def _find_related_entities(self, text: str) -> List[str]:
        """Find entities related to text content"""
        if not self.knowledge_graph:
            return []
        
        # Simple entity matching
        entities = []
        text_lower = text.lower()
        
        for entity in self.knowledge_graph.entities.values():
            if hasattr(entity, 'name') and entity.name.lower() in text_lower:
                entities.append(entity.name)
        
        return entities
    
    def _extract_entities_from_text(self, text: str) -> List[str]:
        """Extract entity names from text"""
        if not self.knowledge_graph:
            return []
        
        entities = []
        text_lower = text.lower()
        
        for entity in self.knowledge_graph.entities.values():
            if hasattr(entity, 'name') and entity.name.lower() in text_lower:
                entities.append(entity.name)
        
        return entities
    
    def _find_relationship(self, entity1: str, entity2: str) -> Optional[str]:
        """Find relationship between two entities"""
        if not self.knowledge_graph:
            return None
        
        for relationship in self.knowledge_graph.relationships.values():
            if (hasattr(relationship.source_entity, 'name') and 
                hasattr(relationship.target_entity, 'name')):
                if (relationship.source_entity.name == entity1 and 
                    relationship.target_entity.name == entity2) or \
                   (relationship.source_entity.name == entity2 and 
                    relationship.target_entity.name == entity1):
                    return relationship.relationship_type
        
        return None
    
    def _generate_search_metadata(
        self,
        content_types: Optional[List[str]],
        temporal_scope: Optional[str], 
        reasoning_depth: str
    ) -> Dict[str, Any]:
        """Generate metadata for search operation"""
        return {
            'content_types_filter': content_types,
            'temporal_scope': temporal_scope,
            'reasoning_depth': reasoning_depth,
            'total_searchable_items': len(self._text_items),
            'graphrag_enabled': self.graphrag is not None,
            'knowledge_graph_available': self.knowledge_graph is not None
        }


# Example usage and testing
if __name__ == "__main__":
    from ipfs_datasets_py.content_discovery import ContentAsset, ContentManifest
    from ipfs_datasets_py.processors.multimodal_processor import ProcessedContent, ProcessedContentBatch
    from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import KnowledgeGraph, Entity, Relationship
    
    def test_website_graphrag_system():
        """Test WebsiteGraphRAGSystem functionality"""
        
        # Create sample processed content
        html_content = ProcessedContent(
            source_url="https://example.com/page1.html",
            content_type="html",
            text_content="This is a test webpage about artificial intelligence and machine learning.",
            metadata={"title": "AI/ML Introduction"},
            confidence_score=0.9
        )
        
        pdf_content = ProcessedContent(
            source_url="https://example.com/paper.pdf", 
            content_type="pdf",
            text_content="Research paper on deep learning algorithms and neural networks.",
            metadata={"title": "Deep Learning Research"},
            confidence_score=0.8
        )
        
        # Create processed content batch
        processed_batch = ProcessedContentBatch(
            base_url="https://example.com",
            processed_items=[html_content, pdf_content],
            processing_stats={'html': 1, 'pdf': 1, 'total': 2}
        )
        
        # Create sample knowledge graph
        ai_entity = Entity(name="Artificial Intelligence", entity_type="concept")
        ml_entity = Entity(name="Machine Learning", entity_type="concept")
        relationship = Relationship(ai_entity, ml_entity, "includes")
        
        knowledge_graph = KnowledgeGraph()
        knowledge_graph.add_entity(ai_entity)
        knowledge_graph.add_entity(ml_entity)
        knowledge_graph.add_relationship(relationship)
        
        # Create sample content manifest
        manifest = ContentManifest(
            base_url="https://example.com",
            html_pages=[],
            pdf_documents=[],
            media_files=[],
            structured_data=[],
            total_assets=2,
            discovery_timestamp=datetime.now()
        )
        
        # Create WebsiteGraphRAGSystem
        system = WebsiteGraphRAGSystem(
            url="https://example.com",
            content_manifest=manifest,
            processed_content=processed_batch,
            knowledge_graph=knowledge_graph,
            graphrag=None  # No GraphRAG for this test
        )
        
        print(f"System initialized for: {system.url}")
        print(f"Content overview: {system.get_content_overview()}")
        
        # Test search
        results = system.query("artificial intelligence machine learning")
        print(f"\nSearch results for 'artificial intelligence machine learning':")
        print(f"Found {results.total_results} results")
        
        for i, result in enumerate(results.results):
            print(f"\nResult {i+1}:")
            print(f"  Title: {result.title}")
            print(f"  Type: {result.content_type}")
            print(f"  Score: {result.relevance_score:.3f}")
            print(f"  Snippet: {result.content_snippet}")
        
        # Test content type filtering
        html_results = system.search_by_content_type('html')
        print(f"\nHTML content items: {len(html_results)}")
        
        # Test dataset export
        dataset_file = system.export_dataset()
        print(f"\nDataset exported to: {dataset_file}")
    
    # Run test
    test_website_graphrag_system()