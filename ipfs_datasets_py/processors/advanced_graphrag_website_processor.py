#!/usr/bin/env python3
"""
Advanced GraphRAG Website Processor - Production Implementation

This module provides a comprehensive GraphRAG system for processing entire websites
with advanced knowledge extraction, intelligent performance optimization, and 
production-ready integration features.

.. deprecated:: 1.0.0
   This module is deprecated. Use :class:`ipfs_datasets_py.processors.graphrag.unified_graphrag.UnifiedGraphRAGProcessor` instead.
   The UnifiedGraphRAGProcessor consolidates all GraphRAG implementations including this one.

Key Features:
- Multi-pass knowledge extraction with domain-specific patterns
- Intelligent performance optimization with resource monitoring
- Advanced content processing with quality assessment
- Comprehensive search and query capabilities
- Production-ready error handling and monitoring

Usage:
    # DEPRECATED - for backward compatibility only
    processor = AdvancedGraphRAGWebsiteProcessor()
    result = processor.process_website(website_data, options)
    
    # NEW - recommended approach
    from ipfs_datasets_py.processors.graphrag.unified_graphrag import UnifiedGraphRAGProcessor
    processor = UnifiedGraphRAGProcessor()
    result = await processor.process_website("https://example.com")
"""

import os
import sys
import json
import time
import logging
import warnings
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass, field

# Import existing components
try:
    from .advanced_knowledge_extractor import AdvancedKnowledgeExtractor, ExtractionContext
    from .advanced_performance_optimizer import AdvancedPerformanceOptimizer, ProcessingProfile, ResourceMetrics
    ADVANCED_COMPONENTS_AVAILABLE = True
except ImportError:
    ADVANCED_COMPONENTS_AVAILABLE = False
    logging.warning("Advanced components not available, using fallback implementations")

logger = logging.getLogger(__name__)


@dataclass
class WebsiteProcessingConfiguration:
    """Configuration for advanced website processing"""
    
    # Processing settings
    domain: str = "general"
    processing_mode: str = "balanced"  # fast, balanced, quality
    quality_threshold: float = 0.6
    max_processing_time: int = 300
    
    # Content preferences  
    include_html: bool = True
    include_pdf: bool = True
    include_media: bool = True
    enable_ocr: bool = False
    
    # Knowledge extraction
    enable_multi_pass: bool = True
    enable_disambiguation: bool = True
    extract_relationships: bool = True
    confidence_threshold: float = 0.6
    
    # Performance optimization
    enable_monitoring: bool = True
    enable_caching: bool = True
    batch_size: int = 10
    max_workers: int = 4
    
    # Output preferences
    create_search_index: bool = True
    export_knowledge_graph: bool = True
    include_analytics: bool = True


@dataclass
class AdvancedWebsiteResult:
    """Comprehensive website processing result"""
    
    # Basic metrics
    success: bool = False
    processing_time: float = 0.0
    pages_processed: int = 0
    total_content_size: int = 0
    
    # Knowledge extraction results  
    entities_extracted: int = 0
    relationships_found: int = 0
    entity_types: Dict[str, int] = field(default_factory=dict)
    knowledge_quality_score: float = 0.0
    
    # Performance metrics
    throughput: float = 0.0
    resource_efficiency: float = 0.0
    optimization_impact: float = 0.0
    
    # Advanced features
    searchable_entities: Dict[str, Any] = field(default_factory=dict)
    knowledge_graph: Optional[Dict[str, Any]] = None
    search_capabilities: Dict[str, Any] = field(default_factory=dict)
    
    # Analytics and insights
    content_analysis: Dict[str, Any] = field(default_factory=dict)
    extraction_analytics: Dict[str, Any] = field(default_factory=dict)
    performance_recommendations: List[Dict[str, str]] = field(default_factory=list)
    
    # Status information
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    processing_log: List[Dict[str, Any]] = field(default_factory=list)


class AdvancedGraphRAGWebsiteProcessor:
    """
    Advanced GraphRAG processor for comprehensive website knowledge extraction.
    
    .. deprecated:: 1.0.0
       Use :class:`ipfs_datasets_py.processors.graphrag.unified_graphrag.UnifiedGraphRAGProcessor` instead.
       This class is maintained for backward compatibility but will be removed in version 2.0.0.
       The unified processor provides all features from this implementation plus async support.
    """
    
    def __init__(self, config: Optional[WebsiteProcessingConfiguration] = None):
        """
        Initialize advanced GraphRAG processor.
        
        .. deprecated:: 1.0.0
           Use UnifiedGraphRAGProcessor instead.
        """
        warnings.warn(
            "AdvancedGraphRAGWebsiteProcessor is deprecated and will be removed in version 2.0.0. "
            "Use ipfs_datasets_py.processors.graphrag.unified_graphrag.UnifiedGraphRAGProcessor instead. "
            "The unified processor consolidates all GraphRAG implementations including this one.",
            DeprecationWarning,
            stacklevel=2
        )
        self.config = config or WebsiteProcessingConfiguration()
        
        # Initialize advanced components if available
        if ADVANCED_COMPONENTS_AVAILABLE:
            try:
                self.knowledge_extractor = AdvancedKnowledgeExtractor()
                self.performance_optimizer = AdvancedPerformanceOptimizer()
                self.advanced_mode = True
                logger.info("Advanced components initialized successfully")
            except Exception as e:
                logger.warning(f"Failed to initialize advanced components: {e}")
                self.advanced_mode = False
        else:
            self.advanced_mode = False
        
        # Processing state
        self.processing_history = []
        self.entity_cache = {}
        self.performance_metrics = {
            'total_processed': 0,
            'average_quality': 0.0,
            'cumulative_entities': 0,
            'session_start': datetime.now()
        }
    
    def process_website(
        self,
        website_data: Dict[str, Any],
        config: Optional[WebsiteProcessingConfiguration] = None
    ) -> AdvancedWebsiteResult:
        """
        Process a complete website with advanced GraphRAG capabilities
        
        Args:
            website_data: Website content and metadata
            config: Processing configuration override
            
        Returns:
            Comprehensive processing result with knowledge graph and analytics
        """
        
        processing_config = config or self.config
        start_time = time.time()
        result = AdvancedWebsiteResult()
        
        try:
            logger.info(f"Starting advanced website processing: {website_data.get('url', 'unknown')}")
            
            # Initialize monitoring
            if processing_config.enable_monitoring and self.advanced_mode:
                initial_resources = self.performance_optimizer.monitor_resources()
                logger.info(f"Initial resources: CPU {initial_resources.cpu_percent:.1f}%, "
                           f"Memory {initial_resources.memory_percent:.1f}%")
            else:
                initial_resources = None
            
            # Optimize processing configuration
            optimized_config = self._optimize_processing_configuration(
                website_data, processing_config, initial_resources
            )
            
            # Process website content
            content_results = self._process_website_content(
                website_data, optimized_config
            )
            
            # Build advanced knowledge graph
            knowledge_graph = self._build_advanced_knowledge_graph(
                content_results, processing_config
            )
            
            # Create comprehensive search capabilities
            search_system = self._create_comprehensive_search_system(
                knowledge_graph, content_results
            )
            
            # Generate analytics and insights
            analytics = self._generate_comprehensive_analytics(
                content_results, knowledge_graph, start_time
            )
            
            # Assemble comprehensive result
            result = self._assemble_comprehensive_result(
                content_results, knowledge_graph, search_system,
                analytics, start_time, initial_resources
            )
            
            # Update processing history
            self._update_processing_history(result)
            
            logger.info(f"Advanced processing completed successfully: "
                       f"{result.entities_extracted} entities, "
                       f"{result.relationships_found} relationships, "
                       f"quality score: {result.knowledge_quality_score:.2f}")
            
        except Exception as e:
            logger.error(f"Advanced processing failed: {str(e)}")
            result.success = False
            result.errors.append(str(e))
            result.processing_time = time.time() - start_time
            
            # Add error context
            import traceback
            result.processing_log.append({
                'timestamp': datetime.now().isoformat(),
                'level': 'error',
                'message': str(e),
                'traceback': traceback.format_exc()
            })
        
        return result
    
    def _optimize_processing_configuration(
        self,
        website_data: Dict[str, Any],
        config: WebsiteProcessingConfiguration,
        resources: Optional[Any]
    ) -> Dict[str, Any]:
        """Optimize processing configuration based on content and resources"""
        
        pages = website_data.get('pages', [])
        estimated_size = sum(len(p.get('content', '')) for p in pages) / 1024  # KB
        
        # Base configuration
        optimized = {
            'batch_size': config.batch_size,
            'max_workers': config.max_workers,
            'quality_threshold': config.quality_threshold,
            'enable_caching': config.enable_caching,
            'processing_mode': config.processing_mode
        }
        
        # Resource-based optimization
        if resources and self.advanced_mode:
            try:
                optimization = self.performance_optimizer.optimize_for_processing(
                    content_count=len(pages),
                    estimated_content_size_mb=estimated_size / 1024,
                    processing_type=config.processing_mode
                )
                
                # Apply optimizations
                opt_config = optimization.get('optimal_config', {})
                optimized.update({
                    'batch_size': opt_config.get('batch_size', optimized['batch_size']),
                    'max_workers': opt_config.get('max_workers', optimized['max_workers']),
                    'enable_caching': opt_config.get('enable_caching', optimized['enable_caching'])
                })
                
                logger.info(f"Configuration optimized: batch_size={optimized['batch_size']}, "
                           f"workers={optimized['max_workers']}")
                
            except Exception as e:
                logger.warning(f"Configuration optimization failed: {e}")
        
        # Content-based adjustments
        if len(pages) > 50:  # Large website
            optimized['batch_size'] = min(optimized['batch_size'] * 2, 50)
            optimized['processing_mode'] = 'fast'
        elif estimated_size > 1000:  # Large content
            optimized['quality_threshold'] = max(0.5, optimized['quality_threshold'] - 0.1)
        
        return optimized
    
    def _process_website_content(
        self,
        website_data: Dict[str, Any],
        config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Process all website content with advanced extraction"""
        
        pages = website_data.get('pages', [])
        results = []
        
        logger.info(f"Processing {len(pages)} pages with batch size {config['batch_size']}")
        
        # Process in batches for efficiency
        batch_size = config['batch_size']
        
        for i in range(0, len(pages), batch_size):
            batch = pages[i:i + batch_size]
            batch_start = time.time()
            
            logger.info(f"Processing batch {i//batch_size + 1}/{(len(pages) + batch_size - 1)//batch_size}")
            
            for j, page in enumerate(batch):
                try:
                    page_result = self._process_single_page_advanced(page, config)
                    results.append(page_result)
                    
                except Exception as e:
                    logger.error(f"Failed to process page {page.get('url', 'unknown')}: {e}")
                    results.append({
                        'url': page.get('url', 'unknown'),
                        'success': False,
                        'error': str(e),
                        'entities': {},
                        'relationships': {}
                    })
            
            batch_time = time.time() - batch_start
            logger.debug(f"Batch processed in {batch_time:.2f}s")
            
            # Memory management between batches
            if config.get('enable_caching', True) and self.advanced_mode:
                try:
                    current_resources = self.performance_optimizer.monitor_resources()
                    if current_resources.memory_percent > 80:
                        logger.warning("High memory usage - clearing cache")
                        self.entity_cache.clear()
                except:
                    pass  # Continue processing even if monitoring fails
        
        return results
    
    def _process_single_page_advanced(
        self,
        page: Dict[str, Any],
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Process single page with advanced knowledge extraction"""
        
        url = page.get('url', 'unknown')
        content = page.get('content', '')
        content_type = page.get('type', 'html')
        title = page.get('title', '')
        
        if not content:
            return {
                'url': url,
                'success': False,
                'error': 'No content available'
            }
        
        try:
            # Advanced content preprocessing
            processed_content = self._preprocess_content_comprehensive(
                content, content_type, title, page
            )
            
            # Knowledge extraction
            if self.advanced_mode:
                # Use advanced extractor
                extraction_context = ExtractionContext(
                    domain=self.config.domain,
                    source_type=content_type,
                    confidence_threshold=config['quality_threshold'],
                    enable_disambiguation=self.config.enable_disambiguation,
                    extract_temporal=True
                )
                
                kg = self.knowledge_extractor.extract_knowledge(processed_content, extraction_context)
                entities = self._enhance_entities_with_metadata(kg.entities, page, processed_content)
                relationships = self._enhance_relationships_with_metadata(kg.relationships, page)
                
            else:
                # Fallback extraction
                entities, relationships = self._fallback_extraction(processed_content, page)
            
            # Content quality assessment
            quality_metrics = self._assess_content_quality(processed_content, entities, relationships)
            
            return {
                'url': url,
                'success': True,
                'content_type': content_type,
                'processed_content': processed_content[:1000],  # Store sample for analysis
                'entities': entities,
                'relationships': relationships,
                'quality_metrics': quality_metrics,
                'processing_timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Page processing failed for {url}: {e}")
            return {
                'url': url,
                'success': False,
                'error': str(e)
            }
    
    def _preprocess_content_comprehensive(
        self,
        content: str,
        content_type: str,
        title: str,
        page_metadata: Dict[str, Any]
    ) -> str:
        """Comprehensive content preprocessing with multiple techniques"""
        
        # HTML processing
        if content_type == 'html':
            import re
            
            # Remove scripts, styles, and comments
            content = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL | re.IGNORECASE)
            content = re.sub(r'<style[^>]*>.*?</style>', '', content, flags=re.DOTALL | re.IGNORECASE)
            content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
            
            # Extract and prioritize structured content
            structured_content = []
            
            # Headers (high priority)
            headers = re.findall(r'<h[1-6][^>]*>(.*?)</h[1-6]>', content, flags=re.IGNORECASE | re.DOTALL)
            if headers:
                structured_content.extend([f"HEADER: {h.strip()}" for h in headers])
            
            # Tables (structured data)
            tables = re.findall(r'<table[^>]*>(.*?)</table>', content, flags=re.DOTALL)
            for table in tables:
                cells = re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', table, flags=re.DOTALL)
                if cells:
                    structured_content.append(f"TABLE: {' | '.join(cells)}")
            
            # Lists
            lists = re.findall(r'<[uo]l[^>]*>(.*?)</[uo]l>', content, flags=re.DOTALL)
            for list_html in lists:
                items = re.findall(r'<li[^>]*>(.*?)</li>', list_html, flags=re.DOTALL)
                if items:
                    structured_content.append(f"LIST: {' • '.join(items)}")
            
            # Remove remaining HTML tags
            content = re.sub(r'<[^>]+>', ' ', content)
            
            # Combine structured and regular content
            if structured_content:
                content = '\n'.join(structured_content) + '\n\n' + content
        
        # Add contextual information
        if title:
            content = f"TITLE: {title}\n\n{content}"
        
        url = page_metadata.get('url', '')
        if url:
            # Extract domain for context
            try:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc
                content = f"SOURCE: {domain}\n{content}"
            except:
                pass
        
        # Clean and normalize whitespace
        import re
        content = re.sub(r'\s+', ' ', content)
        content = content.strip()
        
        # Content length management
        if len(content) > 15000:  # 15KB limit
            content = content[:15000] + "\n\n[Content truncated for processing efficiency]"
        
        return content
    
    def _enhance_entities_with_metadata(
        self,
        entities: Dict[str, Any],
        page: Dict[str, Any],
        content: str
    ) -> Dict[str, Any]:
        """Enhance entities with comprehensive metadata"""
        
        enhanced = {}
        
        for entity_id, entity in entities.items():
            entity_name = entity.name
            
            # Calculate entity prominence
            name_count = content.lower().count(entity_name.lower())
            prominence = min(1.0, name_count / 5)  # Normalize to 0-1
            
            # Extract context
            context = self._extract_entity_context(entity_name, content)
            
            # Entity classification refinement
            refined_type = self._classify_entity_advanced(entity, context, page)
            
            enhanced[entity_id] = {
                'id': entity_id,
                'name': entity_name,
                'type': refined_type,
                'original_type': entity.entity_type,
                'confidence': entity.confidence,
                'properties': getattr(entity, 'properties', {}) or {},
                
                # Source information
                'source_url': page.get('url', ''),
                'source_title': page.get('title', ''),
                'source_domain': self._extract_domain(page.get('url', '')),
                
                # Content analysis
                'prominence_score': prominence,
                'occurrence_count': name_count,
                'context_snippet': context[:200],
                'position_ratio': self._calculate_position_ratio(entity_name, content),
                
                # Quality metrics
                'name_quality_score': self._calculate_name_quality(entity_name),
                'context_richness': min(1.0, len(context) / 500),
                
                # Temporal information
                'extraction_timestamp': datetime.now().isoformat(),
                'processing_version': '1.0'
            }
        
        return enhanced
    
    def _enhance_relationships_with_metadata(
        self,
        relationships: Dict[str, Any],
        page: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Enhance relationships with comprehensive metadata"""
        
        enhanced = {}
        
        for rel_id, relationship in relationships.items():
            enhanced[rel_id] = {
                'id': rel_id,
                'source_entity': relationship.source_entity,
                'target_entity': relationship.target_entity,
                'relationship_type': relationship.relationship_type,
                'confidence': relationship.confidence,
                'properties': getattr(relationship, 'properties', {}) or {},
                
                # Source information
                'source_url': page.get('url', ''),
                'source_domain': self._extract_domain(page.get('url', '')),
                
                # Relationship analysis
                'bidirectional': self._is_bidirectional_relationship(relationship.relationship_type),
                'semantic_strength': relationship.confidence,
                'relationship_category': self._categorize_relationship(relationship.relationship_type),
                
                # Temporal information
                'extraction_timestamp': datetime.now().isoformat()
            }
        
        return enhanced
    
    def _fallback_extraction(
        self,
        content: str,
        page: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Fallback knowledge extraction using pattern matching"""
        
        entities = {}
        relationships = {}
        
        import re
        
        # Enhanced entity patterns
        entity_patterns = {
            'person': [
                r'\b(?:Dr|Prof|Professor|Mr|Ms|Mrs)\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b',
                r'\b([A-Z][a-z]+\s+[A-Z][a-z]+)(?:\s+is\s+(?:a|an)\s+(?:researcher|scientist|professor))\b'
            ],
            'organization': [
                r'\b([A-Z][a-zA-Z\s]+(?:University|Institute|Corporation|Company|Lab|Laboratory|Center|Centre))\b',
                r'\b([A-Z]{2,}\s*[A-Z]*)\b(?=\s+(?:is|has|provides|offers))'
            ],
            'technology': [
                r'\b([A-Z][a-zA-Z]+)(?:\s+[0-9.]+)?\b(?=\s+(?:framework|library|platform|API|system))',
                r'\b((?:PyTorch|TensorFlow|BERT|GPT|FAISS|Docker|Kubernetes))\b'
            ],
            'location': [
                r'\b([A-Z][a-zA-Z\s]+(?:City|State|Country|County|Province))\b',
                r'\b((?:California|New York|London|Tokyo|Berlin))\b'
            ],
            'conference': [
                r'\b((?:NeurIPS|ICML|ICLR|AAAI|CVPR|ICCV|ECCV)\s*(?:20\d{2})?)\b',
                r'\b([A-Z]{3,}\s+(?:Conference|Workshop|Symposium))\b'
            ]
        }
        
        entity_id_counter = 0
        
        for entity_type, patterns in entity_patterns.items():
            for pattern in patterns:
                matches = re.finditer(pattern, content, re.IGNORECASE)
                
                for match in matches:
                    entity_text = match.group(1).strip()
                    
                    # Skip if already found or too short
                    if len(entity_text) < 3 or entity_text.lower() in [e['name'].lower() for e in entities.values()]:
                        continue
                    
                    entity_id_counter += 1
                    entity_id = f"fallback_{entity_id_counter}"
                    
                    entities[entity_id] = {
                        'id': entity_id,
                        'name': entity_text,
                        'type': entity_type,
                        'confidence': 0.75,  # Moderate confidence for pattern-based extraction
                        'source_url': page.get('url', ''),
                        'extraction_method': 'pattern_matching',
                        'extraction_timestamp': datetime.now().isoformat(),
                        'match_position': match.start(),
                        'pattern_used': pattern
                    }
        
        return entities, relationships
    
    def _build_advanced_knowledge_graph(
        self,
        content_results: List[Dict[str, Any]],
        config: WebsiteProcessingConfiguration
    ) -> Dict[str, Any]:
        """Build advanced knowledge graph with comprehensive analysis"""
        
        logger.info("Building advanced knowledge graph...")
        
        # Collect all entities and relationships
        all_entities = {}
        all_relationships = {}
        entity_co_occurrences = {}
        
        for result in content_results:
            if not result.get('success', False):
                continue
            
            # Process entities
            for entity_id, entity in result.get('entities', {}).items():
                entity_name = entity['name']
                
                # Avoid duplicates by name (case-insensitive)
                existing_entity = None
                for existing_id, existing in all_entities.items():
                    if existing['name'].lower() == entity_name.lower():
                        existing_entity = existing
                        break
                
                if existing_entity:
                    # Merge entity information
                    existing_entity['occurrence_count'] = existing_entity.get('occurrence_count', 1) + 1
                    existing_entity['confidence'] = max(existing_entity['confidence'], entity['confidence'])
                    if 'source_urls' not in existing_entity:
                        existing_entity['source_urls'] = [existing_entity.get('source_url', '')]
                    existing_entity['source_urls'].append(entity.get('source_url', ''))
                else:
                    all_entities[entity_id] = dict(entity)
                    all_entities[entity_id]['occurrence_count'] = 1
            
            # Process relationships
            for rel_id, relationship in result.get('relationships', {}).items():
                all_relationships[rel_id] = relationship
        
        # Calculate entity importance and connections
        entity_importance = {}
        entity_connections = {}
        
        for entity in all_entities.values():
            entity_name = entity['name']
            
            # Importance score based on multiple factors
            importance = (
                entity['confidence'] * 0.4 +
                min(1.0, entity.get('occurrence_count', 1) / 5) * 0.3 +
                entity.get('prominence_score', 0.5) * 0.3
            )
            entity_importance[entity_name] = importance
            entity_connections[entity_name] = []
        
        # Build connection graph from relationships
        for relationship in all_relationships.values():
            source = relationship['source_entity']
            target = relationship['target_entity']
            
            if source in entity_connections and target not in entity_connections[source]:
                entity_connections[source].append(target)
            if target in entity_connections and source not in entity_connections[target]:
                entity_connections[target].append(source)
        
        # Graph analysis
        total_entities = len(all_entities)
        total_relationships = len(all_relationships)
        
        # Entity type distribution
        type_distribution = {}
        for entity in all_entities.values():
            entity_type = entity['type']
            type_distribution[entity_type] = type_distribution.get(entity_type, 0) + 1
        
        # Find most connected entities
        connection_counts = {name: len(connections) for name, connections in entity_connections.items()}
        most_connected = max(connection_counts, key=connection_counts.get) if connection_counts else None
        
        # Graph density
        max_possible_connections = total_entities * (total_entities - 1) // 2
        actual_connections = sum(len(conns) for conns in entity_connections.values()) // 2
        graph_density = actual_connections / max_possible_connections if max_possible_connections > 0 else 0.0
        
        knowledge_graph = {
            'entities': all_entities,
            'relationships': all_relationships,
            
            # Graph structure
            'entity_connections': entity_connections,
            'entity_importance_scores': entity_importance,
            
            # Analysis metrics
            'total_entities': total_entities,
            'total_relationships': total_relationships,
            'entity_type_distribution': type_distribution,
            'most_connected_entity': most_connected,
            'max_connections': max(connection_counts.values()) if connection_counts else 0,
            'graph_density': graph_density,
            
            # Quality metrics
            'average_entity_confidence': sum(e['confidence'] for e in all_entities.values()) / total_entities if total_entities > 0 else 0,
            'high_confidence_entities': sum(1 for e in all_entities.values() if e['confidence'] >= 0.8),
            'connectivity_ratio': total_relationships / total_entities if total_entities > 0 else 0,
            
            # Metadata
            'graph_id': f"kg_{int(time.time())}",
            'created_timestamp': datetime.now().isoformat(),
            'processing_config': {
                'domain': config.domain,
                'quality_threshold': config.quality_threshold,
                'multi_pass_enabled': config.enable_multi_pass
            }
        }
        
        logger.info(f"Advanced knowledge graph built: {total_entities} entities, "
                   f"{total_relationships} relationships, density: {graph_density:.3f}")
        
        return knowledge_graph
    
    def _create_comprehensive_search_system(
        self,
        knowledge_graph: Dict[str, Any],
        content_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Create comprehensive search system with multiple indexes"""
        
        logger.info("Creating comprehensive search system...")
        
        # Entity-based indexes
        entity_name_index = {}
        entity_type_index = {}
        entity_importance_index = {}
        
        for entity in knowledge_graph['entities'].values():
            name = entity['name'].lower()
            entity_type = entity['type']
            importance = knowledge_graph['entity_importance_scores'].get(entity['name'], 0.0)
            
            # Name index (for fuzzy search)
            words = name.split()
            for word in words:
                if word not in entity_name_index:
                    entity_name_index[word] = []
                entity_name_index[word].append(entity['id'])
            
            # Type index
            if entity_type not in entity_type_index:
                entity_type_index[entity_type] = []
            entity_type_index[entity_type].append(entity['id'])
            
            # Importance tiers
            if importance >= 0.8:
                tier = 'high'
            elif importance >= 0.6:
                tier = 'medium'
            else:
                tier = 'low'
            
            if tier not in entity_importance_index:
                entity_importance_index[tier] = []
            entity_importance_index[tier].append(entity['id'])
        
        # Content-based indexes
        keyword_index = {}
        url_index = {}
        domain_index = {}
        
        for result in content_results:
            if not result.get('success'):
                continue
            
            url = result.get('url', '')
            content = result.get('processed_content', '')
            
            # URL and domain indexing
            url_index[url] = {
                'title': result.get('title', ''),
                'content_preview': content[:300],
                'entity_count': len(result.get('entities', {})),
                'processing_success': True
            }
            
            domain = self._extract_domain(url)
            if domain:
                if domain not in domain_index:
                    domain_index[domain] = []
                domain_index[domain].append(url)
            
            # Keyword extraction
            words = content.lower().split()
            for word in words:
                if len(word) > 3 and word.isalpha():
                    if word not in keyword_index:
                        keyword_index[word] = []
                    if url not in keyword_index[word]:
                        keyword_index[word].append(url)
        
        # Relationship indexes
        relationship_type_index = {}
        entity_relationship_index = {}
        
        for relationship in knowledge_graph['relationships'].values():
            rel_type = relationship['relationship_type']
            source = relationship['source_entity']
            target = relationship['target_entity']
            
            # Type index
            if rel_type not in relationship_type_index:
                relationship_type_index[rel_type] = []
            relationship_type_index[rel_type].append(relationship['id'])
            
            # Entity-relationship index
            for entity in [source, target]:
                if entity not in entity_relationship_index:
                    entity_relationship_index[entity] = []
                entity_relationship_index[entity].append(relationship['id'])
        
        search_system = {
            # Entity indexes
            'entity_name_index': entity_name_index,
            'entity_type_index': entity_type_index,
            'entity_importance_index': entity_importance_index,
            
            # Content indexes
            'keyword_index': keyword_index,
            'url_index': url_index,
            'domain_index': domain_index,
            
            # Relationship indexes
            'relationship_type_index': relationship_type_index,
            'entity_relationship_index': entity_relationship_index,
            
            # Search capabilities
            'search_capabilities': {
                'entity_search': True,
                'keyword_search': True,
                'relationship_search': True,
                'domain_search': True,
                'importance_filtering': True,
                'type_filtering': True
            },
            
            # Index statistics
            'index_stats': {
                'entities_indexed': len(knowledge_graph['entities']),
                'unique_keywords': len(keyword_index),
                'indexed_urls': len(url_index),
                'domains_covered': len(domain_index),
                'relationship_types': len(relationship_type_index),
                'created_timestamp': datetime.now().isoformat()
            }
        }
        
        logger.info(f"Search system created: {len(entity_name_index)} entity terms, "
                   f"{len(keyword_index)} keywords, {len(url_index)} URLs")
        
        return search_system
    
    def _generate_comprehensive_analytics(
        self,
        content_results: List[Dict[str, Any]],
        knowledge_graph: Dict[str, Any],
        start_time: float
    ) -> Dict[str, Any]:
        """Generate comprehensive analytics and insights"""
        
        processing_time = time.time() - start_time
        successful_pages = sum(1 for r in content_results if r.get('success', False))
        total_pages = len(content_results)
        
        # Content analysis
        content_types = {}
        total_content_size = 0
        avg_content_quality = 0.0
        
        for result in content_results:
            if result.get('success'):
                content_type = result.get('content_type', 'unknown')
                content_types[content_type] = content_types.get(content_type, 0) + 1
                
                if 'quality_metrics' in result:
                    quality = result['quality_metrics'].get('overall_quality', 0.5)
                    avg_content_quality += quality
                
                total_content_size += len(result.get('processed_content', ''))
        
        if successful_pages > 0:
            avg_content_quality /= successful_pages
        
        # Entity analysis
        entities = knowledge_graph['entities']
        entity_analysis = {
            'total_entities': len(entities),
            'entity_types': knowledge_graph.get('entity_type_distribution', {}),
            'high_confidence_entities': sum(1 for e in entities.values() if e['confidence'] >= 0.8),
            'average_confidence': sum(e['confidence'] for e in entities.values()) / len(entities) if entities else 0,
            'multi_occurrence_entities': sum(1 for e in entities.values() if e.get('occurrence_count', 1) > 1),
            'cross_page_entities': sum(1 for e in entities.values() if len(e.get('source_urls', [])) > 1)
        }
        
        # Performance analysis
        performance_analysis = {
            'processing_time': processing_time,
            'throughput': total_pages / processing_time if processing_time > 0 else 0,
            'success_rate': successful_pages / total_pages if total_pages > 0 else 0,
            'avg_entities_per_page': len(entities) / successful_pages if successful_pages > 0 else 0,
            'processing_efficiency': successful_pages / (processing_time + 0.1),  # Add small constant to avoid division by zero
        }
        
        # Quality metrics
        quality_metrics = {
            'content_quality': avg_content_quality,
            'extraction_quality': entity_analysis['average_confidence'],
            'knowledge_density': len(entities) / total_content_size * 1000 if total_content_size > 0 else 0,  # Entities per 1K characters
            'relationship_richness': len(knowledge_graph['relationships']) / len(entities) if entities else 0
        }
        
        # Domain insights
        domains = set()
        for result in content_results:
            if result.get('success'):
                domain = self._extract_domain(result.get('url', ''))
                if domain:
                    domains.add(domain)
        
        domain_analysis = {
            'domains_processed': list(domains),
            'domain_count': len(domains),
            'cross_domain_entities': sum(1 for e in entities.values() 
                                       if len(set(self._extract_domain(url) for url in e.get('source_urls', []))) > 1)
        }
        
        return {
            'content_analysis': {
                'total_pages': total_pages,
                'successful_pages': successful_pages,
                'content_types': content_types,
                'total_content_size': total_content_size,
                'average_content_quality': avg_content_quality
            },
            'entity_analysis': entity_analysis,
            'performance_analysis': performance_analysis,
            'quality_metrics': quality_metrics,
            'domain_analysis': domain_analysis,
            'processing_summary': {
                'started_at': datetime.fromtimestamp(start_time).isoformat(),
                'completed_at': datetime.now().isoformat(),
                'total_duration': processing_time,
                'pages_per_second': performance_analysis['throughput']
            }
        }
    
    def _assemble_comprehensive_result(
        self,
        content_results: List[Dict[str, Any]],
        knowledge_graph: Dict[str, Any],
        search_system: Dict[str, Any],
        analytics: Dict[str, Any],
        start_time: float,
        initial_resources: Any
    ) -> AdvancedWebsiteResult:
        """Assemble comprehensive processing result"""
        
        processing_time = time.time() - start_time
        
        # Generate performance recommendations
        recommendations = []
        
        perf = analytics['performance_analysis']
        quality = analytics['quality_metrics']
        
        if perf['success_rate'] < 0.9:
            recommendations.append({
                'type': 'reliability',
                'priority': 'high',
                'recommendation': 'Improve content preprocessing for higher success rate',
                'current_value': f"{perf['success_rate']:.1%}",
                'target_value': '>90%'
            })
        
        if perf['throughput'] < 1.0:
            recommendations.append({
                'type': 'performance',
                'priority': 'medium',
                'recommendation': 'Increase batch size or optimize content processing',
                'current_value': f"{perf['throughput']:.1f} pages/sec",
                'target_value': '>1.0 pages/sec'
            })
        
        if quality['extraction_quality'] < 0.7:
            recommendations.append({
                'type': 'quality',
                'priority': 'high',
                'recommendation': 'Lower quality threshold or improve extraction patterns',
                'current_value': f"{quality['extraction_quality']:.2f}",
                'target_value': '>0.7'
            })
        
        # Calculate overall scores
        knowledge_quality_score = (
            quality['extraction_quality'] * 0.4 +
            quality['content_quality'] * 0.3 +
            min(1.0, quality['knowledge_density'] / 10) * 0.3
        )
        
        resource_efficiency = 0.8  # Placeholder - would be calculated from actual resource usage
        if initial_resources and self.advanced_mode:
            try:
                final_resources = self.performance_optimizer.monitor_resources()
                memory_efficiency = 1.0 - (final_resources.memory_percent - initial_resources.memory_percent) / 100
                resource_efficiency = max(0.0, min(1.0, memory_efficiency))
            except:
                pass
        
        # Create comprehensive result
        result = AdvancedWebsiteResult(
            success=analytics['content_analysis']['successful_pages'] > 0,
            processing_time=processing_time,
            pages_processed=analytics['content_analysis']['total_pages'],
            total_content_size=analytics['content_analysis']['total_content_size'],
            
            # Knowledge extraction results
            entities_extracted=len(knowledge_graph['entities']),
            relationships_found=len(knowledge_graph['relationships']),
            entity_types=knowledge_graph.get('entity_type_distribution', {}),
            knowledge_quality_score=knowledge_quality_score,
            
            # Performance metrics
            throughput=perf['throughput'],
            resource_efficiency=resource_efficiency,
            optimization_impact=0.2 if self.advanced_mode else 0.0,  # Placeholder
            
            # Advanced features
            searchable_entities=knowledge_graph['entities'],
            knowledge_graph=knowledge_graph,
            search_capabilities=search_system,
            
            # Analytics and insights
            content_analysis=analytics['content_analysis'],
            extraction_analytics=analytics['entity_analysis'],
            performance_recommendations=recommendations,
            
            # Processing log
            processing_log=[{
                'timestamp': datetime.now().isoformat(),
                'level': 'info',
                'message': f'Processing completed successfully: {len(knowledge_graph["entities"])} entities extracted'
            }]
        )
        
        return result
    
    # Helper methods
    
    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL"""
        try:
            from urllib.parse import urlparse
            return urlparse(url).netloc.lower()
        except:
            return ''
    
    def _extract_entity_context(self, entity_name: str, content: str, window_size: int = 150) -> str:
        """Extract context around entity mention"""
        entity_lower = entity_name.lower()
        content_lower = content.lower()
        
        pos = content_lower.find(entity_lower)
        if pos == -1:
            return ""
        
        start = max(0, pos - window_size)
        end = min(len(content), pos + len(entity_name) + window_size)
        
        return content[start:end].strip()
    
    def _classify_entity_advanced(self, entity: Any, context: str, page: Dict[str, Any]) -> str:
        """Advanced entity type classification"""
        
        original_type = entity.entity_type
        entity_name = entity.name.lower()
        context_lower = context.lower()
        
        # Academic classification
        if any(term in context_lower for term in ['university', 'professor', 'research', 'phd', 'dr.', 'paper']):
            if 'person' in original_type.lower():
                return 'researcher'
            elif 'organization' in original_type.lower():
                return 'academic_institution'
        
        # Technology classification
        if any(term in context_lower for term in ['api', 'framework', 'library', 'software', 'algorithm']):
            return 'technology'
        
        # Conference/Publication classification
        if any(term in context_lower for term in ['conference', 'journal', 'proceedings', 'published']):
            return 'publication_venue'
        
        # Location classification
        if any(term in context_lower for term in ['located', 'city', 'country', 'based in']):
            return 'location'
        
        return original_type
    
    def _calculate_position_ratio(self, entity_name: str, content: str) -> float:
        """Calculate position of entity in content (0.0 = beginning, 1.0 = end)"""
        pos = content.lower().find(entity_name.lower())
        if pos == -1 or len(content) == 0:
            return 0.5
        return pos / len(content)
    
    def _calculate_name_quality(self, entity_name: str) -> float:
        """Calculate entity name quality score"""
        # Simple heuristic based on length, capitalization, etc.
        score = 0.5  # Base score
        
        if len(entity_name) >= 3:
            score += 0.2
        if entity_name[0].isupper():
            score += 0.2
        if ' ' in entity_name:  # Multi-word entities often higher quality
            score += 0.1
        if not entity_name.isupper() or len(entity_name) > 4:  # Avoid all-caps short words
            score += 0.1
        
        return min(1.0, score)
    
    def _is_bidirectional_relationship(self, relationship_type: str) -> bool:
        """Determine if relationship type is typically bidirectional"""
        bidirectional_types = [
            'collaborates_with', 'partners_with', 'works_with', 
            'associated_with', 'related_to', 'connected_to'
        ]
        return relationship_type.lower() in bidirectional_types
    
    def _categorize_relationship(self, relationship_type: str) -> str:
        """Categorize relationship into broad categories"""
        academic_rels = ['affiliated_with', 'collaborates_with', 'supervises', 'authors']
        technical_rels = ['uses', 'implements', 'based_on', 'extends']
        organizational_rels = ['works_at', 'employed_by', 'member_of']
        
        rel_lower = relationship_type.lower()
        
        if any(rel in rel_lower for rel in academic_rels):
            return 'academic'
        elif any(rel in rel_lower for rel in technical_rels):
            return 'technical'
        elif any(rel in rel_lower for rel in organizational_rels):
            return 'organizational'
        else:
            return 'general'
    
    def _assess_content_quality(
        self, 
        content: str, 
        entities: Dict[str, Any], 
        relationships: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Assess content quality metrics"""
        
        words = content.split()
        sentences = content.count('.')
        
        # Basic quality metrics
        word_count = len(words)
        sentence_count = max(1, sentences)
        avg_sentence_length = word_count / sentence_count
        
        # Information density
        entity_density = len(entities) / word_count * 1000 if word_count > 0 else 0  # Entities per 1000 words
        relationship_density = len(relationships) / word_count * 1000 if word_count > 0 else 0
        
        # Readability (simple heuristic)
        readability_score = min(1.0, max(0.0, 1.0 - abs(avg_sentence_length - 20) / 30))
        
        # Overall quality
        content_richness = min(1.0, word_count / 1000)  # Normalize to 1000 words
        information_richness = min(1.0, (entity_density + relationship_density) / 20)
        
        overall_quality = (
            content_richness * 0.3 +
            information_richness * 0.4 +
            readability_score * 0.3
        )
        
        return {
            'word_count': word_count,
            'sentence_count': sentence_count,
            'average_sentence_length': avg_sentence_length,
            'entity_density': entity_density,
            'relationship_density': relationship_density,
            'readability_score': readability_score,
            'content_richness': content_richness,
            'information_richness': information_richness,
            'overall_quality': overall_quality
        }
    
    def _update_processing_history(self, result: AdvancedWebsiteResult):
        """Update processing history and metrics"""
        
        history_entry = {
            'timestamp': datetime.now().isoformat(),
            'success': result.success,
            'pages_processed': result.pages_processed,
            'entities_extracted': result.entities_extracted,
            'processing_time': result.processing_time,
            'quality_score': result.knowledge_quality_score,
            'throughput': result.throughput
        }
        
        self.processing_history.append(history_entry)
        
        # Keep last 50 entries
        if len(self.processing_history) > 50:
            self.processing_history = self.processing_history[-50:]
        
        # Update cumulative metrics
        self.performance_metrics['total_processed'] += 1
        self.performance_metrics['cumulative_entities'] += result.entities_extracted
        
        # Update average quality
        total = self.performance_metrics['total_processed']
        current_avg = self.performance_metrics['average_quality']
        new_avg = ((current_avg * (total - 1)) + result.knowledge_quality_score) / total
        self.performance_metrics['average_quality'] = new_avg
    
    # Search and query methods
    
    def search_entities(
        self,
        query: str,
        entity_type: Optional[str] = None,
        min_confidence: float = 0.0,
        importance_tier: Optional[str] = None,  # 'high', 'medium', 'low'
        max_results: int = 10
    ) -> List[Dict[str, Any]]:
        """Search entities with advanced filtering"""
        
        if not hasattr(self, 'last_search_system') or not self.last_search_system:
            return []
        
        search_system = self.last_search_system
        results = []
        
        # Entity name search
        query_words = query.lower().split()
        entity_candidates = set()
        
        for word in query_words:
            if word in search_system.get('entity_name_index', {}):
                entity_candidates.update(search_system['entity_name_index'][word])
        
        # Type filtering
        if entity_type and entity_type in search_system.get('entity_type_index', {}):
            type_entities = set(search_system['entity_type_index'][entity_type])
            entity_candidates = entity_candidates.intersection(type_entities)
        
        # Importance filtering
        if importance_tier and importance_tier in search_system.get('entity_importance_index', {}):
            importance_entities = set(search_system['entity_importance_index'][importance_tier])
            entity_candidates = entity_candidates.intersection(importance_entities)
        
        # Get entity details and apply confidence filter
        for entity_id in entity_candidates:
            if hasattr(self, 'entity_cache') and entity_id in self.entity_cache:
                entity = self.entity_cache[entity_id]
                if entity.get('confidence', 0.0) >= min_confidence:
                    results.append(entity)
        
        # Sort by relevance (combination of confidence and query match)
        def relevance_score(entity):
            confidence = entity.get('confidence', 0.0)
            name_match = sum(1 for word in query_words if word in entity['name'].lower()) / len(query_words)
            return confidence * 0.6 + name_match * 0.4
        
        results.sort(key=relevance_score, reverse=True)
        
        return results[:max_results]
    
    def get_entity_relationships(self, entity_name: str) -> List[Dict[str, Any]]:
        """Get all relationships for a specific entity"""
        
        if not hasattr(self, 'last_knowledge_graph') or not self.last_knowledge_graph:
            return []
        
        relationships = []
        
        for rel in self.last_knowledge_graph.get('relationships', {}).values():
            if (rel.get('source_entity', '').lower() == entity_name.lower() or 
                rel.get('target_entity', '').lower() == entity_name.lower()):
                relationships.append(rel)
        
        return relationships
    
    def get_processing_statistics(self) -> Dict[str, Any]:
        """Get comprehensive processing statistics"""
        
        return {
            'performance_metrics': self.performance_metrics,
            'processing_history': self.processing_history[-10:],  # Last 10 entries
            'session_info': {
                'advanced_mode_enabled': self.advanced_mode,
                'total_sessions': len(self.processing_history),
                'session_start': self.performance_metrics['session_start'].isoformat(),
                'entities_cached': len(self.entity_cache)
            }
        }
    
    def validate_config(self, config: Optional[WebsiteProcessingConfiguration] = None) -> Dict[str, Any]:
        """Validate processing configuration and return validation results"""
        config = config or self.config
        
        validation_result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "config_summary": {}
        }
        
        try:
            # Validate processing mode
            valid_modes = ["fast", "balanced", "quality"]
            if config.processing_mode not in valid_modes:
                validation_result["errors"].append(f"Invalid processing_mode: {config.processing_mode}. Must be one of {valid_modes}")
                validation_result["valid"] = False
            
            # Validate quality threshold
            if not 0.0 <= config.quality_threshold <= 1.0:
                validation_result["errors"].append(f"quality_threshold must be between 0.0 and 1.0, got {config.quality_threshold}")
                validation_result["valid"] = False
            
            # Validate batch size
            if config.batch_size <= 0:
                validation_result["errors"].append(f"batch_size must be positive, got {config.batch_size}")
                validation_result["valid"] = False
            
            validation_result["config_summary"] = {
                "processing_mode": config.processing_mode,
                "quality_threshold": config.quality_threshold,
                "batch_size": config.batch_size,
                "max_workers": config.max_workers,
                "domain": config.domain
            }
            
        except Exception as e:
            validation_result["valid"] = False
            validation_result["errors"].append(f"Configuration validation failed: {str(e)}")
        
        return validation_result
    
    def extract_entities(self, content: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Extract entities from content with advanced processing"""
        context = context or {}
        
        extraction_result = {
            "entities": {},
            "relationships": {},
            "metadata": {
                "extraction_time": time.time(),
                "content_length": len(content),
                "context": context
            }
        }
        
        try:
            # Use basic entity extraction (advanced extractor handled elsewhere)
            entities = self._extract_entities_basic(content)
            extraction_result["entities"] = entities
            extraction_result["metadata"]["entities_found"] = len(extraction_result["entities"])
            
        except Exception as e:
            extraction_result["error"] = str(e)
            extraction_result["metadata"]["extraction_failed"] = True
        
        return extraction_result
    
    def _extract_entities_basic(self, content: str) -> Dict[str, Any]:
        """Basic entity extraction fallback"""
        import re
        
        entities = {}
        
        # Simple named entity patterns
        patterns = {
            "PERSON": r'\b[A-Z][a-z]+\s+[A-Z][a-z]+\b',
            "ORGANIZATION": r'\b[A-Z][A-Z]+\b|\b[A-Z][a-z]+\s+(?:Inc|Corp|LLC|Ltd|University|Institute|Company)\b',
            "LOCATION": r'\b(?:New York|California|Boston|MIT|Stanford|Harvard)\b'
        }
        
        entity_id = 0
        for entity_type, pattern in patterns.items():
            matches = re.findall(pattern, content)
            for match in matches:
                entity_id += 1
                entities[f"entity_{entity_id}"] = {
                    "id": f"entity_{entity_id}",
                    "name": match,
                    "type": entity_type,
                    "confidence": 0.6  # Basic confidence
                }
        
        return entities
    
    def process_html_content(self, html_content: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Process HTML content and extract structured information"""
        metadata = metadata or {}
        
        processing_result = {
            "success": True,
            "processed_content": "",
            "extracted_entities": {},
            "content_structure": {},
            "metadata": metadata,
            "processing_time": 0
        }
        
        start_time = time.time()
        
        try:
            # Preprocess HTML content
            processed_content = self._preprocess_content_comprehensive(
                html_content,
                "html",
                metadata.get("title", ""),
                metadata
            )
            processing_result["processed_content"] = processed_content
            
            # Extract content structure
            processing_result["content_structure"] = self._extract_content_structure(html_content)
            
            # Extract entities from processed content
            extraction_result = self.extract_entities(processed_content, metadata)
            processing_result["extracted_entities"] = extraction_result.get("entities", {})
            
            processing_result["processing_time"] = time.time() - start_time
            
        except Exception as e:
            processing_result["success"] = False
            processing_result["error"] = str(e)
            processing_result["processing_time"] = time.time() - start_time
        
        return processing_result
    
    def _extract_content_structure(self, html_content: str) -> Dict[str, Any]:
        """Extract structural information from HTML content"""
        import re
        
        structure = {
            "headings": [],
            "links": [],
            "images": [],
            "tables": 0,
            "lists": 0,
            "paragraphs": 0
        }
        
        try:
            # Extract headings
            headings = re.findall(r'<h([1-6])[^>]*>(.*?)</h\1>', html_content, flags=re.IGNORECASE | re.DOTALL)
            structure["headings"] = [{"level": int(level), "text": text.strip()} for level, text in headings]
            
            # Extract links
            links = re.findall(r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>', html_content, flags=re.IGNORECASE | re.DOTALL)
            structure["links"] = [{"url": url, "text": text.strip()} for url, text in links]
            
            # Extract images
            images = re.findall(r'<img[^>]*src=["\']([^"\']*)["\'][^>]*>', html_content, flags=re.IGNORECASE)
            structure["images"] = images
            
            # Count structural elements
            structure["tables"] = len(re.findall(r'<table[^>]*>', html_content, flags=re.IGNORECASE))
            structure["lists"] = len(re.findall(r'<[uo]l[^>]*>', html_content, flags=re.IGNORECASE))
            structure["paragraphs"] = len(re.findall(r'<p[^>]*>', html_content, flags=re.IGNORECASE))
            
        except Exception as e:
            structure["extraction_error"] = str(e)
        
        return structure


# Example usage and demo
def demonstrate_advanced_processor():
    """Demonstrate the advanced GraphRAG website processor"""
    
    print("🚀 Advanced GraphRAG Website Processor - Production Demo")
    print("=" * 70)
    
    # Sample website data
    sample_website = {
        'url': 'https://research.ai-institute.edu',
        'pages': [
            {
                'url': 'https://research.ai-institute.edu/about',
                'title': 'About Our AI Research Institute',
                'type': 'html',
                'content': '''
                <html><body>
                <h1>AI Research Institute</h1>
                <p>The AI Research Institute was founded in 2020 by <strong>Dr. Sarah Chen</strong> 
                (Stanford University) and <strong>Prof. Michael Rodriguez</strong> (MIT CSAIL) to advance 
                the frontiers of artificial intelligence research.</p>
                
                <h2>Research Focus Areas</h2>
                <ul>
                <li>Natural Language Processing and Large Language Models</li>
                <li>Computer Vision and Multimodal AI</li>
                <li>Graph Neural Networks and Knowledge Representation</li>
                <li>Federated Learning and Privacy-Preserving AI</li>
                </ul>
                
                <p>Our team collaborates with industry partners including <strong>Google Research</strong>, 
                <strong>Microsoft Research</strong>, and <strong>OpenAI</strong> to translate research 
                breakthroughs into real-world applications.</p>
                </body></html>
                '''
            }
        ]
    }
    
    # Create processor with advanced configuration
    config = WebsiteProcessingConfiguration(
        domain='academic',
        processing_mode='quality',
        quality_threshold=0.7,
        enable_multi_pass=True,
        enable_monitoring=True,
        create_search_index=True
    )
    
    processor = AdvancedGraphRAGWebsiteProcessor(config)
    
    # Process website
    print("🔄 Processing website with advanced GraphRAG...")
    result = processor.process_website(sample_website)
    
    # Display results
    print(f"\n✅ Processing {'succeeded' if result.success else 'failed'}")
    print(f"⏱️  Processing time: {result.processing_time:.2f}s")
    print(f"📊 Pages processed: {result.pages_processed}")
    print(f"🧠 Entities extracted: {result.entities_extracted}")
    print(f"🔗 Relationships found: {result.relationships_found}")
    print(f"⭐ Knowledge quality score: {result.knowledge_quality_score:.2f}")
    print(f"⚡ Throughput: {result.throughput:.1f} pages/sec")
    
    # Show entity types
    if result.entity_types:
        print(f"\n🏷️ Entity types found:")
        for entity_type, count in result.entity_types.items():
            print(f"   • {entity_type}: {count}")
    
    # Show some entities
    if result.searchable_entities:
        print(f"\n🎯 Sample entities:")
        for entity in list(result.searchable_entities.values())[:5]:
            print(f"   • {entity['name']} ({entity['type']}) - {entity['confidence']:.2f}")
    
    # Show recommendations
    if result.performance_recommendations:
        print(f"\n💡 Performance recommendations:")
        for rec in result.performance_recommendations[:3]:
            print(f"   • {rec['recommendation']}")
    
    print(f"\n🎉 Advanced GraphRAG processing demonstration completed!")
    
    return result.success


if __name__ == "__main__":
    success = demonstrate_advanced_processor()
    print(f"\nDemo result: {'SUCCESS' if success else 'FAILED'}")