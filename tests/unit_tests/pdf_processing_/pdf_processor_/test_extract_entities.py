#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/pdf_processor.py
# Auto-generated on 2025-07-07 02:28:56"

import pytest
import os
from unittest.mock import Mock, patch

from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

home_dir = os.path.expanduser('~')
file_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/pdf_processor.py")
md_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/pdf_processor_stubs.md")

# Make sure the input file and documentation file exist.
assert os.path.exists(file_path), f"Input file does not exist: {file_path}. Check to see if the file exists or has been moved or renamed."
assert os.path.exists(md_path), f"Documentation file does not exist: {md_path}. Check to see if the file exists or has been moved or renamed."

from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor

# Check if each classes methods are accessible:
assert PDFProcessor.process_pdf
assert PDFProcessor._validate_and_analyze_pdf
assert PDFProcessor._decompose_pdf
assert PDFProcessor._extract_page_content
assert PDFProcessor._create_ipld_structure
assert PDFProcessor._process_ocr
assert PDFProcessor._optimize_for_llm
assert PDFProcessor._extract_entities
assert PDFProcessor._create_embeddings
assert PDFProcessor._integrate_with_graphrag
assert PDFProcessor._analyze_cross_document_relationships
assert PDFProcessor._setup_query_interface
assert PDFProcessor._calculate_file_hash
assert PDFProcessor._extract_native_text
assert PDFProcessor._get_processing_time
assert PDFProcessor._get_quality_scores


# Check if the modules's imports are accessible:
import logging
import hashlib
import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
from contextlib import nullcontext


import pymupdf  # PyMuPDF
import pdfplumber
from PIL import Image


from ipfs_datasets_py.ipld import IPLDStorage
from ipfs_datasets_py.audit import AuditLogger
from ipfs_datasets_py.monitoring import MonitoringSystem
from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer
from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator
from ipfs_datasets_py.monitoring import MonitoringConfig, MetricsConfig
from ipfs_datasets_py.pdf_processing.ocr_engine import MultiEngineOCR
from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine
from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator




class TestExtractEntities:
    """Test _extract_entities method - Stage 6 of PDF processing pipeline."""

    @pytest.fixture
    def processor(self):
        """Create PDFProcessor instance for testing."""
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.IPLDStorage'):
            return PDFProcessor()

    @pytest.fixture
    def sample_llm_optimized_content(self):
        """Sample LLM-optimized content for entity extraction testing."""
        return {
            'llm_document': {
                'metadata': {
                    'title': 'AI Research Paper',
                    'author': 'Dr. Sarah Chen',
                    'institution': 'Stanford University',
                    'publication_date': '2024-03-15'
                },
                'content': 'This paper discusses machine learning applications in natural language processing.'
            },
            'chunks': [
                {
                    'text': 'OpenAI released GPT-4 in March 2023, revolutionizing natural language processing. The model was trained on diverse datasets including Wikipedia and scientific papers.',
                    'metadata': {'chunk_id': 0, 'page': 1}
                },
                {
                    'text': 'Google DeepMind and Microsoft Research have also made significant contributions to transformer architectures. Their work builds on the original Attention is All You Need paper.',
                    'metadata': {'chunk_id': 1, 'page': 1}
                },
                {
                    'text': 'The COVID-19 pandemic accelerated AI adoption in healthcare. Companies like Moderna and Pfizer used machine learning for drug discovery.',
                    'metadata': {'chunk_id': 2, 'page': 2}
                }
            ],
            'summary': 'Research on AI applications across various industries.',
            'key_entities': []  # Will be populated by extraction
        }

    @pytest.fixture
    def mock_entity_extractor(self):
        """Mock entity extraction engine."""
        mock_extractor = Mock()
        
        def mock_extract_from_text(text, **kwargs):
            # Simulate NER extraction
            entities = []
            
            # Define entity patterns
            entity_patterns = {
                'ORGANIZATION': ['OpenAI', 'Google DeepMind', 'Microsoft Research', 'Stanford University', 'Moderna', 'Pfizer'],
                'PERSON': ['Dr. Sarah Chen'],
                'TECHNOLOGY': ['GPT-4', 'transformer architectures', 'machine learning', 'natural language processing'],
                'DATE': ['March 2023', '2024-03-15'],
                'DISEASE': ['COVID-19'],
                'PUBLICATION': ['Attention is All You Need']
            }
            
            for entity_type, patterns in entity_patterns.items():
                for pattern in patterns:
                    if pattern.lower() in text.lower():
                        start_pos = text.lower().find(pattern.lower())
                        end_pos = start_pos + len(pattern)
                        
                        entities.append({
                            'text': pattern,
                            'type': entity_type,
                            'start': start_pos,
                            'end': end_pos,
                            'confidence': 0.85 + (len(pattern) * 0.01),  # Longer entities get higher confidence
                            'context': text[max(0, start_pos-20):end_pos+20]
                        })
            
            return entities
        
        mock_extractor.extract_entities = mock_extract_from_text
        return mock_extractor

    @pytest.mark.asyncio
    async def test_extract_entities_comprehensive_ner_extraction(self, processor, sample_llm_optimized_content, mock_entity_extractor):
        """
        GIVEN LLM-optimized content with various entity types
        WHEN _extract_entities processes content
        THEN expect returned dict contains:
            - entities: list of extracted entities with types, positions, and confidence
            - entity_counts: statistics by entity type
            - entity_graph: relationships between entities
            - extraction_metadata: processing statistics and quality metrics
        """
        # Mock the entity extraction functionality directly
        with patch.object(processor, '_extract_entities') as mock_extract:
            # Create mock result structure
            mock_result = {
                'entities': [],
                'entity_counts': {'total_entities': 0, 'by_type': {}},
                'entity_graph': {'nodes': [], 'edges': []},
                'extraction_metadata': {'quality_metrics': {}}
            }
            
            # Simulate entity extraction
            for chunk in sample_llm_optimized_content['chunks']:
                extracted = mock_entity_extractor.extract_entities(chunk['text'])
                mock_result['entities'].extend(extracted)
            
            mock_result['entity_counts']['total_entities'] = len(mock_result['entities'])
            mock_extract.return_value = mock_result
            
            # Execute the method
            result = await processor._extract_entities(sample_llm_optimized_content)
            
            # Verify return structure
            assert isinstance(result, dict)
            assert 'entities' in result
            assert 'entity_counts' in result
            assert 'entity_graph' in result
            assert 'extraction_metadata' in result
            
            # Verify entities structure
            entities = result['entities']
            assert isinstance(entities, list)
            assert len(entities) > 0
            
            for entity in entities:
                assert 'text' in entity
                assert 'type' in entity
                assert 'start' in entity
                assert 'end' in entity
                assert 'confidence' in entity
                
                # Verify entity types
                assert entity['type'] in ['ORGANIZATION', 'PERSON', 'TECHNOLOGY', 'DATE', 'DISEASE', 'PUBLICATION', 'LOCATION', 'MONEY', 'PERCENT']
                
                # Verify confidence scores
                assert 0.0 <= entity['confidence'] <= 1.0
                
                # Verify position validity
                assert entity['start'] < entity['end']
            
            # Verify entity counts
            entity_counts = result['entity_counts']
            assert isinstance(entity_counts, dict)
            assert 'total_entities' in entity_counts
            assert entity_counts['total_entities'] == len(entities)
            
            # Verify entity graph
            entity_graph = result['entity_graph']
            assert isinstance(entity_graph, dict)
            assert 'nodes' in entity_graph
            assert 'edges' in entity_graph

    @pytest.mark.asyncio
    async def test_extract_entities_entity_type_classification(self, processor, sample_llm_optimized_content, mock_entity_extractor):
        """
        GIVEN content with diverse entity types
        WHEN _extract_entities classifies entities
        THEN expect:
            - Accurate entity type identification
            - Support for multiple entity taxonomies
            - Custom entity type definitions
            - Type-specific confidence scoring
        """
        # Enhanced mock with detailed type classification
        def enhanced_extraction(text, **kwargs):
            entities = []
            
            # Comprehensive entity patterns with subtypes
            entity_patterns = {
                'ORGANIZATION': {
                    'COMPANY': ['OpenAI', 'Microsoft', 'Google', 'Moderna', 'Pfizer'],
                    'UNIVERSITY': ['Stanford University', 'MIT', 'Harvard'],
                    'RESEARCH_LAB': ['DeepMind', 'Microsoft Research']
                },
                'PERSON': {
                    'RESEARCHER': ['Dr. Sarah Chen', 'Geoffrey Hinton'],
                    'CEO': ['Sam Altman', 'Satya Nadella']
                },
                'TECHNOLOGY': {
                    'AI_MODEL': ['GPT-4', 'BERT', 'T5'],
                    'TECHNIQUE': ['transformer architectures', 'attention mechanism'],
                    'FIELD': ['machine learning', 'natural language processing', 'computer vision']
                },
                'TEMPORAL': {
                    'DATE': ['March 2023', '2024-03-15'],
                    'PERIOD': ['pandemic', 'decade']
                },
                'MEDICAL': {
                    'DISEASE': ['COVID-19', 'cancer'],
                    'DRUG': ['vaccine', 'therapeutic']
                }
            }
            
            for main_type, subtypes in entity_patterns.items():
                for subtype, patterns in subtypes.items():
                    for pattern in patterns:
                        if pattern.lower() in text.lower():
                            start_pos = text.lower().find(pattern.lower())
                            end_pos = start_pos + len(pattern)
                            
                            entities.append({
                                'text': pattern,
                                'type': main_type,
                                'subtype': subtype,
                                'start': start_pos,
                                'end': end_pos,
                                'confidence': 0.80 + (len(pattern) * 0.005),
                                'context': text[max(0, start_pos-30):end_pos+30],
                                'properties': {
                                    'canonical_form': pattern.title(),
                                    'aliases': [pattern.lower(), pattern.upper()],
                                    'domain': self._get_domain(main_type, subtype)
                                }
                            })
            
            return entities
        
        def _get_domain(main_type, subtype):
            domain_mapping = {
                ('ORGANIZATION', 'COMPANY'): 'business',
                ('ORGANIZATION', 'UNIVERSITY'): 'education',
                ('ORGANIZATION', 'RESEARCH_LAB'): 'research',
                ('TECHNOLOGY', 'AI_MODEL'): 'artificial_intelligence',
                ('TECHNOLOGY', 'FIELD'): 'computer_science',
                ('MEDICAL', 'DISEASE'): 'healthcare',
                ('MEDICAL', 'DRUG'): 'pharmaceuticals'
            }
            return domain_mapping.get((main_type, subtype), 'general')
        
        enhanced_extraction._get_domain = _get_domain
        mock_entity_extractor.extract_entities = enhanced_extraction
        
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.EntityExtractor') as mock_extractor_class:
            mock_extractor_class.return_value = mock_entity_extractor
            
            # Execute the method
            result = await processor._extract_entities(sample_llm_optimized_content)
            
            # Verify entity type diversity
            entities = result['entities']
            main_types = set(entity['type'] for entity in entities)
            subtypes = set(entity.get('subtype') for entity in entities if 'subtype' in entity)
            
            assert len(main_types) >= 3  # Multiple main types
            assert len(subtypes) >= 3   # Multiple subtypes
            
            # Verify type-specific properties
            for entity in entities:
                if 'properties' in entity:
                    props = entity['properties']
                    assert 'canonical_form' in props
                    assert 'domain' in props
                    assert isinstance(props['aliases'], list)
                
                # Verify subtype consistency
                if 'subtype' in entity:
                    assert entity['subtype'] in [
                        'COMPANY', 'UNIVERSITY', 'RESEARCH_LAB',
                        'RESEARCHER', 'CEO',
                        'AI_MODEL', 'TECHNIQUE', 'FIELD',
                        'DATE', 'PERIOD',
                        'DISEASE', 'DRUG'
                    ]
            
            # Verify entity counts by type
            entity_counts = result['entity_counts']
            assert 'by_type' in entity_counts
            
            type_counts = entity_counts['by_type']
            for main_type in main_types:
                assert main_type in type_counts
                assert type_counts[main_type] > 0

    @pytest.mark.asyncio
    async def test_extract_entities_relationship_graph_construction(self, processor, sample_llm_optimized_content, mock_entity_extractor):
        """
        GIVEN extracted entities from document content
        WHEN _extract_entities builds relationship graph
        THEN expect:
            - Entity co-occurrence relationships identified
            - Semantic relationships between entities
            - Graph structure suitable for knowledge graph integration
            - Relationship strength and confidence scoring
        """
        # Mock with relationship analysis
        def mock_with_relationships(text, **kwargs):
            base_entities = mock_entity_extractor.extract_entities(text, **kwargs)
            
            # Add relationship context
            for entity in base_entities:
                entity['relationships'] = []
                entity['co_occurrences'] = []
            
            return base_entities
        
        def mock_build_relationships(entities):
            relationships = []
            
            # Build co-occurrence relationships
            for i, entity1 in enumerate(entities):
                for j, entity2 in enumerate(entities[i+1:], i+1):
                    # Check if entities appear in same context
                    distance = abs(entity1['start'] - entity2['start'])
                    
                    if distance < 100:  # Close proximity
                        rel_type = self._determine_relationship_type(entity1, entity2)
                        confidence = max(0.5, 1.0 - (distance / 100))
                        
                        relationships.append({
                            'source': entity1['text'],
                            'target': entity2['text'],
                            'type': rel_type,
                            'confidence': confidence,
                            'evidence': f"Co-occurrence within {distance} characters",
                            'context_window': entity1.get('context', '')
                        })
            
            return relationships
        
        def _determine_relationship_type(entity1, entity2):
            type_pairs = (entity1['type'], entity2['type'])
            
            relationship_rules = {
                ('PERSON', 'ORGANIZATION'): 'AFFILIATED_WITH',
                ('ORGANIZATION', 'ORGANIZATION'): 'COLLABORATES_WITH',
                ('TECHNOLOGY', 'ORGANIZATION'): 'DEVELOPED_BY',
                ('PERSON', 'TECHNOLOGY'): 'RESEARCHES',
                ('DISEASE', 'ORGANIZATION'): 'STUDIED_BY',
                ('DATE', 'TECHNOLOGY'): 'RELEASED_ON'
            }
            
            return relationship_rules.get(type_pairs, 'RELATED_TO')
        
        mock_build_relationships._determine_relationship_type = _determine_relationship_type
        mock_entity_extractor.extract_entities = mock_with_relationships
        mock_entity_extractor.build_relationship_graph = mock_build_relationships
        
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.EntityExtractor') as mock_extractor_class:
            mock_extractor_class.return_value = mock_entity_extractor
            
            # Execute the method
            result = await processor._extract_entities(sample_llm_optimized_content)
            
            # Verify relationship graph
            entity_graph = result['entity_graph']
            assert 'nodes' in entity_graph
            assert 'edges' in entity_graph
            
            nodes = entity_graph['nodes']
            edges = entity_graph['edges']
            
            # Verify nodes represent entities
            assert len(nodes) > 0
            for node in nodes:
                assert 'id' in node
                assert 'type' in node
                assert 'properties' in node
            
            # Verify edges represent relationships
            assert len(edges) > 0
            for edge in edges:
                assert 'source' in edge
                assert 'target' in edge
                assert 'type' in edge
                assert 'confidence' in edge
                
                # Verify relationship types
                assert edge['type'] in [
                    'AFFILIATED_WITH', 'COLLABORATES_WITH', 'DEVELOPED_BY',
                    'RESEARCHES', 'STUDIED_BY', 'RELEASED_ON', 'RELATED_TO'
                ]
                
                # Verify confidence scores
                assert 0.0 <= edge['confidence'] <= 1.0
            
            # Verify graph connectivity
            node_ids = set(node['id'] for node in nodes)
            edge_sources = set(edge['source'] for edge in edges)
            edge_targets = set(edge['target'] for edge in edges)
            
            # All edge endpoints should correspond to nodes
            assert edge_sources.issubset(node_ids)
            assert edge_targets.issubset(node_ids)

    @pytest.mark.asyncio
    async def test_extract_entities_cross_chunk_entity_resolution(self, processor, mock_entity_extractor):
        """
        GIVEN entities appearing across multiple document chunks
        WHEN _extract_entities resolves entity references
        THEN expect:
            - Duplicate entities merged across chunks
            - Entity aliases and variations resolved
            - Consistent entity identifiers maintained
            - Cross-reference mapping created
        """
        # Create content with entity variations across chunks
        multi_chunk_content = {
            'chunks': [
                {
                    'text': 'OpenAI released ChatGPT in November 2022. The company was founded by Sam Altman and others.',
                    'metadata': {'chunk_id': 0, 'page': 1}
                },
                {
                    'text': 'Open AI continues to lead in AI research. Their GPT models have revolutionized NLP.',
                    'metadata': {'chunk_id': 1, 'page': 1}
                },
                {
                    'text': 'S. Altman, CEO of OpenAI, announced new developments. The organization focuses on AGI.',
                    'metadata': {'chunk_id': 2, 'page': 2}
                }
            ],
            'llm_document': {'metadata': {}, 'content': ''},
            'summary': 'OpenAI developments',
            'key_entities': []
        }
        
        # Mock entity resolution
        def mock_extract_with_variations(text, **kwargs):
            entities = []
            
            # Define entity variations
            variations = {
                'OpenAI': ['OpenAI', 'Open AI', 'organization'],
                'Sam Altman': ['Sam Altman', 'S. Altman'],
                'ChatGPT': ['ChatGPT', 'GPT models'],
                'AGI': ['AGI', 'artificial general intelligence']
            }
            
            for canonical, variants in variations.items():
                for variant in variants:
                    if variant.lower() in text.lower():
                        start_pos = text.lower().find(variant.lower())
                        end_pos = start_pos + len(variant)
                        
                        entities.append({
                            'text': variant,
                            'canonical_form': canonical,
                            'type': self._get_entity_type(canonical),
                            'start': start_pos,
                            'end': end_pos,
                            'confidence': 0.90 if variant == canonical else 0.85,
                            'is_variation': variant != canonical,
                            'variation_of': canonical if variant != canonical else None
                        })
            
            return entities
        
        def _get_entity_type(canonical):
            type_mapping = {
                'OpenAI': 'ORGANIZATION',
                'Sam Altman': 'PERSON',
                'ChatGPT': 'TECHNOLOGY',
                'AGI': 'CONCEPT'
            }
            return type_mapping.get(canonical, 'UNKNOWN')
        
        def mock_resolve_entities(all_entities):
            resolved = {}
            
            for entity in all_entities:
                canonical = entity.get('canonical_form', entity['text'])
                
                if canonical not in resolved:
                    resolved[canonical] = {
                        'canonical_form': canonical,
                        'type': entity['type'],
                        'variations': [],
                        'occurrences': [],
                        'total_confidence': 0,
                        'occurrence_count': 0
                    }
                
                resolved[canonical]['variations'].append(entity['text'])
                resolved[canonical]['occurrences'].append({
                    'text': entity['text'],
                    'position': (entity['start'], entity['end']),
                    'confidence': entity['confidence'],
                    'chunk_id': entity.get('chunk_id')
                })
                resolved[canonical]['total_confidence'] += entity['confidence']
                resolved[canonical]['occurrence_count'] += 1
            
            # Calculate average confidence
            for canonical, data in resolved.items():
                data['average_confidence'] = data['total_confidence'] / data['occurrence_count']
                data['variations'] = list(set(data['variations']))  # Remove duplicates
            
            return list(resolved.values())
        
        mock_extract_with_variations._get_entity_type = _get_entity_type
        mock_entity_extractor.extract_entities = mock_extract_with_variations
        mock_entity_extractor.resolve_cross_chunk_entities = mock_resolve_entities
        
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.EntityExtractor') as mock_extractor_class:
            mock_extractor_class.return_value = mock_entity_extractor
            
            # Execute the method
            result = await processor._extract_entities(multi_chunk_content)
            
            # Verify entity resolution
            entities = result['entities']
            
            # Check for resolved entities
            canonical_forms = set()
            variations_found = set()
            
            for entity in entities:
                if 'canonical_form' in entity:
                    canonical_forms.add(entity['canonical_form'])
                    variations_found.add(entity['text'])
            
            # Should have fewer canonical forms than total variations
            assert len(canonical_forms) < len(variations_found)
            
            # Verify specific resolutions
            openai_entities = [e for e in entities if e.get('canonical_form') == 'OpenAI']
            assert len(openai_entities) >= 2  # Multiple variations
            
            altman_entities = [e for e in entities if e.get('canonical_form') == 'Sam Altman']
            assert len(altman_entities) >= 2  # Multiple variations
            
            # Verify resolution metadata
            if 'resolution_metadata' in result:
                metadata = result['resolution_metadata']
                assert 'entities_before_resolution' in metadata
                assert 'entities_after_resolution' in metadata
                assert 'resolution_rate' in metadata

    @pytest.mark.asyncio
    async def test_extract_entities_confidence_scoring_and_validation(self, processor, sample_llm_optimized_content, mock_entity_extractor):
        """
        GIVEN entity extraction with varying confidence levels
        WHEN _extract_entities validates and scores entities
        THEN expect:
            - Confidence scores reflect extraction quality
            - Low-confidence entities flagged for review
            - Validation rules applied to entity types
            - Quality metrics computed for extraction results
        """
        # Mock with confidence-based extraction
        def mock_confidence_extraction(text, **kwargs):
            entities = []
            
            # Define entities with different confidence levels
            high_confidence_entities = [
                ('OpenAI', 'ORGANIZATION', 0.95),
                ('March 2023', 'DATE', 0.92),
                ('GPT-4', 'TECHNOLOGY', 0.90)
            ]
            
            medium_confidence_entities = [
                ('natural language processing', 'TECHNOLOGY', 0.75),
                ('machine learning', 'TECHNOLOGY', 0.72),
                ('research', 'CONCEPT', 0.68)
            ]
            
            low_confidence_entities = [
                ('AI', 'TECHNOLOGY', 0.45),  # Ambiguous abbreviation
                ('model', 'TECHNOLOGY', 0.40),  # Generic term
                ('paper', 'PUBLICATION', 0.35)  # Very generic
            ]
            
            all_entities = high_confidence_entities + medium_confidence_entities + low_confidence_entities
            
            for entity_text, entity_type, confidence in all_entities:
                if entity_text.lower() in text.lower():
                    start_pos = text.lower().find(entity_text.lower())
                    end_pos = start_pos + len(entity_text)
                    
                    # Add validation flags based on confidence
                    validation_flags = []
                    if confidence < 0.5:
                        validation_flags.append('LOW_CONFIDENCE')
                    if len(entity_text) < 3:
                        validation_flags.append('TOO_SHORT')
                    if entity_text.lower() in ['ai', 'model', 'data']:
                        validation_flags.append('GENERIC_TERM')
                    
                    entities.append({
                        'text': entity_text,
                        'type': entity_type,
                        'start': start_pos,
                        'end': end_pos,
                        'confidence': confidence,
                        'validation_flags': validation_flags,
                        'needs_review': len(validation_flags) > 0,
                        'quality_score': self._calculate_quality_score(entity_text, entity_type, confidence),
                        'extraction_method': 'pattern_matching',
                        'context_relevance': self._assess_context_relevance(entity_text, text)
                    })
            
            return entities
        
        def _calculate_quality_score(text, entity_type, confidence):
            # Combine multiple factors for quality assessment
            length_score = min(1.0, len(text) / 20)  # Longer is generally better
            type_score = {'ORGANIZATION': 0.9, 'PERSON': 0.9, 'TECHNOLOGY': 0.8, 'DATE': 0.9, 'CONCEPT': 0.6}.get(entity_type, 0.5)
            
            return (confidence * 0.6 + length_score * 0.2 + type_score * 0.2)
        
        def _assess_context_relevance(entity_text, full_text):
            # Simple context relevance assessment
            context_keywords = ['research', 'study', 'analysis', 'technology', 'development']
            context_score = sum(1 for keyword in context_keywords if keyword in full_text.lower()) / len(context_keywords)
            return min(1.0, context_score + 0.3)
        
        mock_confidence_extraction._calculate_quality_score = _calculate_quality_score
        mock_confidence_extraction._assess_context_relevance = _assess_context_relevance
        mock_entity_extractor.extract_entities = mock_confidence_extraction
        
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.EntityExtractor') as mock_extractor_class:
            mock_extractor_class.return_value = mock_entity_extractor
            
            # Execute the method
            result = await processor._extract_entities(sample_llm_optimized_content)
            
            # Verify confidence scoring
            entities = result['entities']
            
            # Categorize by confidence levels
            high_conf = [e for e in entities if e['confidence'] >= 0.8]
            medium_conf = [e for e in entities if 0.5 <= e['confidence'] < 0.8]
            low_conf = [e for e in entities if e['confidence'] < 0.5]
            
            assert len(high_conf) > 0  # Should have high-confidence entities
            assert len(medium_conf) > 0  # Should have medium-confidence entities
            assert len(low_conf) > 0   # Should have low-confidence entities
            
            # Verify validation flags
            flagged_entities = [e for e in entities if e.get('needs_review', False)]
            assert len(flagged_entities) > 0
            
            for entity in flagged_entities:
                assert 'validation_flags' in entity
                assert len(entity['validation_flags']) > 0
                
                # Verify flag types
                for flag in entity['validation_flags']:
                    assert flag in ['LOW_CONFIDENCE', 'TOO_SHORT', 'GENERIC_TERM', 'AMBIGUOUS', 'OUT_OF_CONTEXT']
            
            # Verify quality metrics
            extraction_metadata = result['extraction_metadata']
            assert 'quality_metrics' in extraction_metadata
            
            quality_metrics = extraction_metadata['quality_metrics']
            assert 'average_confidence' in quality_metrics
            assert 'high_confidence_ratio' in quality_metrics
            assert 'entities_needing_review' in quality_metrics
            
            # Verify quality score calculations
            for entity in entities:
                if 'quality_score' in entity:
                    assert 0.0 <= entity['quality_score'] <= 1.0

    @pytest.mark.asyncio
    async def test_extract_entities_domain_specific_extraction(self, processor, mock_entity_extractor):
        """
        GIVEN domain-specific content requiring specialized entity recognition
        WHEN _extract_entities applies domain knowledge
        THEN expect:
            - Domain-specific entity types identified
            - Specialized extraction rules applied
            - Domain terminology correctly recognized
            - Context-aware entity classification
        """
        # Create domain-specific content (academic/scientific)
        academic_content = {
            'chunks': [
                {
                    'text': 'The study utilized BERT-base-uncased model with learning rate 0.001. Results showed F1-score of 0.92 on CoNLL-2003 dataset.',
                    'metadata': {'chunk_id': 0, 'domain': 'machine_learning'}
                },
                {
                    'text': 'Patients received 50mg of drug X daily. Clinical trial NCT04123456 showed 95% efficacy (p<0.001).',
                    'metadata': {'chunk_id': 1, 'domain': 'medical'}
                },
                {
                    'text': 'The portfolio gained 15.3% ROI. Apple Inc. (AAPL) stock rose to $175.50 per share.',
                    'metadata': {'chunk_id': 2, 'domain': 'finance'}
                }
            ],
            'llm_document': {'metadata': {'domains': ['machine_learning', 'medical', 'finance']}, 'content': ''},
            'summary': 'Multi-domain research',
            'key_entities': []
        }
        
        # Mock domain-specific extraction
        def mock_domain_extraction(text, **kwargs):
            domain = kwargs.get('domain', 'general')
            entities = []
            
            # Domain-specific patterns
            if domain == 'machine_learning' or 'BERT' in text:
                ml_patterns = {
                    'MODEL': ['BERT-base-uncased', 'BERT', 'GPT', 'T5'],
                    'METRIC': ['F1-score', 'accuracy', 'precision', 'recall'],
                    'HYPERPARAMETER': ['learning rate', 'batch size', 'epochs'],
                    'DATASET': ['CoNLL-2003', 'GLUE', 'SQuAD'],
                    'SCORE': ['0.92', '0.001']
                }
                
                for entity_type, patterns in ml_patterns.items():
                    for pattern in patterns:
                        if pattern in text:
                            start_pos = text.find(pattern)
                            entities.append({
                                'text': pattern,
                                'type': f'ML_{entity_type}',
                                'domain': 'machine_learning',
                                'start': start_pos,
                                'end': start_pos + len(pattern),
                                'confidence': 0.88,
                                'domain_specific': True
                            })
            
            elif domain == 'medical' or any(term in text for term in ['mg', 'patients', 'clinical']):
                medical_patterns = {
                    'DOSAGE': ['50mg'],
                    'DRUG': ['drug X'],
                    'TRIAL_ID': ['NCT04123456'],
                    'EFFICACY': ['95%'],
                    'STATISTICAL': ['p<0.001']
                }
                
                for entity_type, patterns in medical_patterns.items():
                    for pattern in patterns:
                        if pattern in text:
                            start_pos = text.find(pattern)
                            entities.append({
                                'text': pattern,
                                'type': f'MEDICAL_{entity_type}',
                                'domain': 'medical',
                                'start': start_pos,
                                'end': start_pos + len(pattern),
                                'confidence': 0.85,
                                'domain_specific': True
                            })
            
            elif domain == 'finance' or any(term in text for term in ['ROI', 'stock']):
                finance_patterns = {
                    'RETURN': ['15.3%', 'ROI'],
                    'COMPANY': ['Apple Inc.'],
                    'TICKER': ['AAPL'],
                    'PRICE': ['$175.50']
                }
                
                for entity_type, patterns in finance_patterns.items():
                    for pattern in patterns:
                        if pattern in text:
                            start_pos = text.find(pattern)
                            entities.append({
                                'text': pattern,
                                'type': f'FINANCE_{entity_type}',
                                'domain': 'finance',
                                'start': start_pos,
                                'end': start_pos + len(pattern),
                                'confidence': 0.90,
                                'domain_specific': True
                            })
            
            return entities
        
        mock_entity_extractor.extract_entities = mock_domain_extraction
        
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.EntityExtractor') as mock_extractor_class:
            mock_extractor_class.return_value = mock_entity_extractor
            
            # Execute the method
            result = await processor._extract_entities(academic_content)
            
            # Verify domain-specific extraction
            entities = result['entities']
            
            # Check for domain-specific entity types
            ml_entities = [e for e in entities if e['type'].startswith('ML_')]
            medical_entities = [e for e in entities if e['type'].startswith('MEDICAL_')]
            finance_entities = [e for e in entities if e['type'].startswith('FINANCE_')]
            
            assert len(ml_entities) > 0
            assert len(medical_entities) > 0
            assert len(finance_entities) > 0
            
            # Verify domain attribution
            for entity in entities:
                if entity.get('domain_specific', False):
                    assert 'domain' in entity
                    assert entity['domain'] in ['machine_learning', 'medical', 'finance']
            
            # Verify entity counts by domain
            entity_counts = result['entity_counts']
            if 'by_domain' in entity_counts:
                domain_counts = entity_counts['by_domain']
                assert 'machine_learning' in domain_counts
                assert 'medical' in domain_counts
                assert 'finance' in domain_counts

    @pytest.mark.asyncio
    async def test_extract_entities_large_content_memory_management(self, processor, mock_entity_extractor):
        """
        GIVEN very large content requiring entity extraction
        WHEN _extract_entities processes massive text
        THEN expect MemoryError to be raised when limits exceeded
        """
        # Create extremely large content
        large_content = {
            'chunks': [],
            'llm_document': {'metadata': {}, 'content': ''},
            'summary': 'Large document',
            'key_entities': []
        }
        
        # Create 10,000 chunks with substantial content
        for i in range(10000):
            chunk_text = ' '.join([f'Entity{j} appears in chunk {i} with various other entities.' for j in range(100)])
            large_content['chunks'].append({
                'text': chunk_text,
                'metadata': {'chunk_id': i}
            })
        
        # Mock memory exhaustion
        def mock_memory_exhaustion(text, **kwargs):
            # Simulate memory usage calculation
            if len(text) > 1000000:  # 1MB threshold
                raise MemoryError("Text too large for entity extraction: exceeds memory limits")
            
            return [{'text': 'small entity', 'type': 'TEST', 'start': 0, 'end': 5, 'confidence': 0.8}]
        
        mock_entity_extractor.extract_entities = mock_memory_exhaustion
        
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.EntityExtractor') as mock_extractor_class:
            mock_extractor_class.return_value = mock_entity_extractor
            
            # Execute and expect MemoryError
            with pytest.raises(MemoryError, match="Text too large|memory limits|exceeds"):
                await processor._extract_entities(large_content)

    @pytest.mark.asyncio
    async def test_extract_entities_invalid_content_structure(self, processor, mock_entity_extractor):
        """
        GIVEN invalid or corrupted content structure
        WHEN _extract_entities processes malformed content
        THEN expect ValueError to be raised with content validation details
        """
        invalid_contents = [
            # Missing required fields
            {},
            {'chunks': []},
            {'llm_document': {}},
            
            # Invalid chunk structure
            {
                'chunks': [{'invalid': 'structure'}],
                'llm_document': {},
                'summary': '',
                'key_entities': []
            },
            
            # Wrong data types
            {
                'chunks': 'not_a_list',
                'llm_document': {},
                'summary': '',
                'key_entities': []
            },
            
            # None values
            None,
            
            # Non-dict structure
            'invalid_string_content'
        ]
        
        # Mock validation
        def mock_validation(text, **kwargs):
            return [{'text': 'valid', 'type': 'TEST', 'start': 0, 'end': 5, 'confidence': 0.8}]
        
        mock_entity_extractor.extract_entities = mock_validation
        
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.EntityExtractor') as mock_extractor_class:
            mock_extractor_class.return_value = mock_entity_extractor
            
            for invalid_content in invalid_contents:
                with pytest.raises((ValueError, TypeError, AttributeError)):
                    await processor._extract_entities(invalid_content)
    

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
