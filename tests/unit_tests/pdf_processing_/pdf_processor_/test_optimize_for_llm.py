#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/pdf_processor.py
# Auto-generated on 2025-07-07 02:28:56"

import pytest
import os
from unittest.mock import patch, Mock

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



class TestOptimizeForLlm:
    """Test _optimize_for_llm method - Stage 5 of PDF processing pipeline."""

    @pytest.fixture
    def processor(self):
        """Create PDFProcessor instance for testing."""
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.IPLDStorage'):
            return PDFProcessor()

    @pytest.fixture
    def sample_decomposed_content(self):
        """Sample decomposed PDF content for testing."""
        return {
            'pages': [
                {
                    'page_number': 1,
                    'elements': [
                        {'type': 'text', 'content': 'Introduction to Machine Learning', 'bbox': [0, 0, 200, 30]},
                        {'type': 'text', 'content': 'Machine learning is a subset of artificial intelligence that focuses on algorithms.', 'bbox': [0, 40, 500, 60]},
                        {'type': 'text', 'content': 'Key concepts include supervised learning, unsupervised learning, and reinforcement learning.', 'bbox': [0, 70, 520, 90]}
                    ],
                    'text_blocks': [
                        {'content': 'Introduction to Machine Learning', 'bbox': [0, 0, 200, 30]},
                        {'content': 'Machine learning is a subset of artificial intelligence that focuses on algorithms. Key concepts include supervised learning, unsupervised learning, and reinforcement learning.', 'bbox': [0, 40, 520, 90]}
                    ],
                    'images': [],
                    'annotations': []
                },
                {
                    'page_number': 2,
                    'elements': [
                        {'type': 'text', 'content': 'Applications and Examples', 'bbox': [0, 0, 180, 30]},
                        {'type': 'text', 'content': 'Common applications include natural language processing, computer vision, and recommendation systems.', 'bbox': [0, 40, 540, 60]}
                    ],
                    'text_blocks': [
                        {'content': 'Applications and Examples', 'bbox': [0, 0, 180, 30]},
                        {'content': 'Common applications include natural language processing, computer vision, and recommendation systems.', 'bbox': [0, 40, 540, 60]}
                    ],
                    'images': [],
                    'annotations': []
                }
            ],
            'metadata': {
                'title': 'Machine Learning Fundamentals',
                'author': 'Dr. AI Researcher',
                'pages': 2,
                'created': '2025-01-01'
            }
        }

    @pytest.fixture
    def sample_ocr_results(self):
        """Sample OCR results for testing."""
        return {
            'page_1': {
                'images': [
                    {
                        'text': 'Figure 1: Neural Network Architecture',
                        'confidence': 0.92,
                        'words': [
                            {'text': 'Figure', 'confidence': 0.95, 'bbox': [10, 10, 50, 25]},
                            {'text': '1:', 'confidence': 0.98, 'bbox': [55, 10, 70, 25]},
                            {'text': 'Neural', 'confidence': 0.90, 'bbox': [75, 10, 115, 25]},
                            {'text': 'Network', 'confidence': 0.88, 'bbox': [120, 10, 170, 25]},
                            {'text': 'Architecture', 'confidence': 0.92, 'bbox': [175, 10, 250, 25]}
                        ],
                        'engine': 'easyocr'
                    }
                ]
            },
            'page_2': {
                'images': []
            }
        }

    @pytest.fixture
    def mock_llm_optimizer(self):
        """Mock LLM optimizer for testing."""
        mock_optimizer = Mock()
        
        def mock_create_chunks(content, **kwargs):
            # Simulate intelligent chunking
            chunks = []
            words = content.split()
            chunk_size = kwargs.get('chunk_size', 50)
            
            for i in range(0, len(words), chunk_size):
                chunk_words = words[i:i + chunk_size]
                chunk_text = ' '.join(chunk_words)
                
                chunks.append({
                    'text': chunk_text,
                    'metadata': {
                        'chunk_id': i // chunk_size,
                        'word_count': len(chunk_words),
                        'start_position': i,
                        'semantic_types': 'paragraph'
                    }
                })
            
            return chunks
        
        def mock_summarize(content, **kwargs):
            # Simple summarization
            sentences = content.split('.')[:3]  # First 3 sentences
            return '. '.join(sentences) + '.'
        
        mock_optimizer.create_chunks = mock_create_chunks
        mock_optimizer.summarize_document = mock_summarize
        mock_optimizer.extract_entities = Mock(return_value=[
            {'text': 'Machine Learning', 'type': 'CONCEPT', 'position': [0, 16]},
            {'text': 'artificial intelligence', 'type': 'CONCEPT', 'position': [45, 68]}
        ])
        
        return mock_optimizer

    @pytest.mark.asyncio
    async def test_optimize_for_llm_complete_content_transformation(self, processor, sample_decomposed_content, sample_ocr_results, mock_llm_optimizer):
        """
        GIVEN decomposed content and OCR results with mixed content types
        WHEN _optimize_for_llm processes content
        THEN expect returned dict contains:
            - llm_document: structured LLMDocument with chunks and metadata
            - chunks: list of optimized LLMChunk objects
            - summary: document-level summary for context
            - key_entities: extracted entities with types and positions
        """
        # Mock the LLM optimizer
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.LLMOptimizer') as mock_optimizer_class:
            mock_optimizer_class.return_value = mock_llm_optimizer
            
            # Execute the method
            result = await processor._optimize_for_llm(sample_decomposed_content, sample_ocr_results)
            
            # Verify return structure
            assert isinstance(result, dict)
            assert 'llm_document' in result
            assert 'chunks' in result
            assert 'summary' in result
            assert 'key_entities' in result
            
            # Verify LLM document structure
            llm_document = result['llm_document']
            assert isinstance(llm_document, dict)
            assert 'metadata' in llm_document
            assert 'content' in llm_document
            
            # Verify chunks
            chunks = result['chunks']
            assert isinstance(chunks, list)
            assert len(chunks) > 0
            
            for chunk in chunks:
                assert 'text' in chunk
                assert 'metadata' in chunk
                assert len(chunk['text']) > 0
            
            # Verify summary
            summary = result['summary']
            assert isinstance(summary, str)
            assert len(summary) > 0
            
            # Verify entities
            entities = result['key_entities']
            assert isinstance(entities, list)
            assert len(entities) > 0
            
            for entity in entities:
                assert 'text' in entity
                assert 'type' in entity
                assert 'position' in entity

    @pytest.mark.asyncio
    async def test_optimize_for_llm_intelligent_chunking_strategy(self, processor, mock_llm_optimizer):
        """
        GIVEN long document content requiring chunking
        WHEN _optimize_for_llm applies chunking strategy
        THEN expect:
            - Semantic coherence preserved across chunks
            - Context boundaries respected
            - Optimal chunk sizes for LLM consumption
            - Overlap strategies maintaining continuity
        """
        # Create long document content
        long_content = {
            'pages': [
                {
                    'page_number': 1,
                    'text_blocks': [
                        {'content': ' '.join([f'This is sentence {i} in a very long document that needs to be chunked intelligently.' for i in range(100)])}
                    ],
                    'elements': [],
                    'images': [],
                    'annotations': []
                }
            ],
            'metadata': {'title': 'Long Document', 'pages': 1}
        }
        
        ocr_results = {'page_1': {'images': []}}
        
        # Mock chunking with overlap
        def mock_smart_chunking(content, **kwargs):
            chunks = []
            sentences = content.split('.')
            chunk_size = 20  # sentences per chunk
            overlap = 3     # sentences overlap
            
            for i in range(0, len(sentences), chunk_size - overlap):
                chunk_sentences = sentences[i:i + chunk_size]
                chunk_text = '.'.join(chunk_sentences)
                
                chunks.append({
                    'text': chunk_text,
                    'metadata': {
                        'chunk_id': len(chunks),
                        'sentence_count': len(chunk_sentences),
                        'overlap_start': max(0, i),
                        'overlap_end': min(len(sentences), i + chunk_size),
                        'semantic_coherence_score': 0.85
                    }
                })
            
            return chunks
        
        mock_llm_optimizer.create_chunks = mock_smart_chunking
        
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.LLMOptimizer') as mock_optimizer_class:
            mock_optimizer_class.return_value = mock_llm_optimizer
            
            # Execute the method
            result = await processor._optimize_for_llm(long_content, ocr_results)
            
            # Verify intelligent chunking
            chunks = result['chunks']
            assert len(chunks) > 1  # Should create multiple chunks
            
            # Verify chunk overlap and continuity
            for i, chunk in enumerate(chunks):
                metadata = chunk['metadata']
                
                # Verify chunk metadata
                assert 'chunk_id' in metadata
                assert 'semantic_coherence_score' in metadata
                assert metadata['semantic_coherence_score'] > 0.8
                
                # Verify reasonable chunk size
                assert len(chunk['text']) > 100  # Not too small
                assert len(chunk['text']) < 5000  # Not too large
                
                # Verify overlap if not last chunk
                if i < len(chunks) - 1:
                    assert 'overlap_end' in metadata
                    assert metadata['overlap_end'] > metadata['overlap_start']

    @pytest.mark.asyncio
    async def test_optimize_for_llm_ocr_text_integration(self, processor, sample_decomposed_content, mock_llm_optimizer):
        """
        GIVEN native PDF text and OCR results from images
        WHEN _optimize_for_llm integrates text sources
        THEN expect:
            - OCR text seamlessly merged with native text
            - Content positioning maintained
            - Quality differences handled appropriately
            - Unified text representation created
        """
        # OCR results with mixed quality
        ocr_results = {
            'page_1': {
                'images': [
                    {
                        'text': 'High quality OCR text from diagram',
                        'confidence': 0.95,
                        'bbox': [100, 100, 400, 150],
                        'words': [
                            {'text': 'High', 'confidence': 0.98, 'bbox': [100, 100, 130, 120]},
                            {'text': 'quality', 'confidence': 0.95, 'bbox': [135, 100, 180, 120]}
                        ]
                    },
                    {
                        'text': 'L0w qu4l1ty 0CR t3xt',
                        'confidence': 0.45,
                        'bbox': [100, 200, 300, 250],
                        'words': [
                            {'text': 'L0w', 'confidence': 0.40, 'bbox': [100, 200, 130, 220]},
                            {'text': 'qu4l1ty', 'confidence': 0.35, 'bbox': [135, 200, 180, 220]}
                        ]
                    }
                ]
            },
            'page_2': {'images': []}
        }
        
        # Mock integrated text processing
        def mock_integrate_text(native_content, ocr_content, **kwargs):
            integrated_chunks = []
            
            # Process native text
            for page in native_content['pages']:
                for block in page.get('text_blocks', []):
                    integrated_chunks.append({
                        'text': block['content'],
                        'metadata': {
                            'source': 'native_pdf',
                            'quality': 'high',
                            'confidence': 1.0,
                            'page': page['page_number']
                        }
                    })
            
            # Process OCR text based on quality
            for page_key, page_ocr in ocr_content.items():
                page_num = int(page_key.split('_')[1])
                for image in page_ocr.get('images', []):
                    if image['confidence'] > 0.7:  # High quality OCR
                        integrated_chunks.append({
                            'text': image['text'],
                            'metadata': {
                                'source': 'ocr_high_quality',
                                'quality': 'high',
                                'confidence': image['confidence'],
                                'page': page_num
                            }
                        })
                    else:  # Low quality OCR - may need post-processing
                        integrated_chunks.append({
                            'text': image['text'],
                            'metadata': {
                                'source': 'ocr_low_quality',
                                'quality': 'low',
                                'confidence': image['confidence'],
                                'page': page_num,
                                'needs_review': True
                            }
                        })
            
            return integrated_chunks
        
        mock_llm_optimizer.create_chunks = mock_integrate_text
        
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.LLMOptimizer') as mock_optimizer_class:
            mock_optimizer_class.return_value = mock_llm_optimizer
            
            # Execute the method
            result = await processor._optimize_for_llm(sample_decomposed_content, ocr_results)
            
            # Verify text integration
            chunks = result['chunks']
            
            # Check for different source types
            native_chunks = [c for c in chunks if c['metadata'].get('source') == 'native_pdf']
            ocr_high_chunks = [c for c in chunks if c['metadata'].get('source') == 'ocr_high_quality']
            ocr_low_chunks = [c for c in chunks if c['metadata'].get('source') == 'ocr_low_quality']
            
            assert len(native_chunks) > 0  # Should have native text
            assert len(ocr_high_chunks) > 0  # Should have high quality OCR
            assert len(ocr_low_chunks) > 0  # Should have low quality OCR
            
            # Verify quality handling
            for chunk in ocr_high_chunks:
                assert chunk['metadata']['confidence'] > 0.7
                assert chunk['metadata']['quality'] == 'high'
            
            for chunk in ocr_low_chunks:
                assert chunk['metadata']['confidence'] <= 0.7
                assert chunk['metadata']['quality'] == 'low'
                assert chunk['metadata'].get('needs_review') is True
            
            # Verify unified representation
            for chunk in chunks:
                assert 'text' in chunk
                assert 'metadata' in chunk
                assert 'source' in chunk['metadata']
                assert 'page' in chunk['metadata']

    @pytest.mark.asyncio
    async def test_optimize_for_llm_document_summarization(self, processor, sample_decomposed_content, sample_ocr_results, mock_llm_optimizer):
        """
        GIVEN complete document content for summarization
        WHEN _optimize_for_llm generates document summary
        THEN expect:
            - Concise summary capturing key points
            - Summary suitable for context and retrieval
            - Main themes and topics identified
            - Summary length appropriate for document size
        """
        # Mock advanced summarization
        def mock_advanced_summarization(content, **kwargs):
            # Extract key sentences and concepts
            sentences = content.split('.')
            key_sentences = [s for s in sentences if any(keyword in s.lower() for keyword in ['machine learning', 'artificial intelligence', 'algorithm', 'application'])]
            
            summary = '. '.join(key_sentences[:3]) + '.'
            
            return {
                'summary': summary,
                'key_themes': ['Machine Learning', 'Artificial Intelligence', 'Applications'],
                'main_topics': ['supervised learning', 'unsupervised learning', 'natural language processing'],
                'summary_length': len(summary),
                'compression_ratio': len(summary) / len(content)
            }
        
        mock_llm_optimizer.summarize_document = mock_advanced_summarization
        
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.LLMOptimizer') as mock_optimizer_class:
            mock_optimizer_class.return_value = mock_llm_optimizer
            
            # Execute the method
            result = await processor._optimize_for_llm(sample_decomposed_content, sample_ocr_results)
            
            # Verify summarization
            summary = result['summary']
            assert isinstance(summary, str)
            assert len(summary) > 50  # Substantial summary
            assert len(summary) < 1000  # But not too long
            
            # Verify key concepts are captured
            summary_lower = summary.lower()
            assert 'machine learning' in summary_lower or 'artificial intelligence' in summary_lower
            
            # Check for summary metadata if available
            llm_document = result['llm_document']
            if 'summary_metadata' in llm_document:
                metadata = llm_document['summary_metadata']
                assert 'key_themes' in metadata
                assert 'main_topics' in metadata
                assert 'compression_ratio' in metadata
                
                # Verify themes and topics
                assert isinstance(metadata['key_themes'], list)
                assert isinstance(metadata['main_topics'], list)
                assert len(metadata['key_themes']) > 0
                assert len(metadata['main_topics']) > 0

    @pytest.mark.asyncio
    async def test_optimize_for_llm_entity_extraction_during_optimization(self, processor, sample_decomposed_content, sample_ocr_results, mock_llm_optimizer):
        """
        GIVEN content being optimized for LLM consumption
        WHEN _optimize_for_llm extracts entities during processing
        THEN expect:
            - Key entities identified with types and positions
            - Entity extraction integrated with content structuring
            - Entity information preserved through optimization
            - Entities support downstream knowledge graph construction
        """
        # Mock comprehensive entity extraction
        def mock_entity_extraction(content, **kwargs):
            entities = [
                {
                    'text': 'Machine Learning',
                    'type': 'TECHNOLOGY',
                    'position': [0, 16],
                    'confidence': 0.95,
                    'context': 'Introduction to Machine Learning',
                    'properties': {'field': 'Computer Science', 'category': 'AI Subdomain'}
                },
                {
                    'text': 'Dr. AI Researcher',
                    'type': 'PERSON',
                    'position': [150, 167],
                    'confidence': 0.92,
                    'context': 'Author information',
                    'properties': {'role': 'Author', 'title': 'Dr.'}
                },
                {
                    'text': 'artificial intelligence',
                    'type': 'TECHNOLOGY',
                    'position': [45, 68],
                    'confidence': 0.88,
                    'context': 'Machine learning is a subset of artificial intelligence',
                    'properties': {'field': 'Computer Science', 'category': 'Main Domain'}
                },
                {
                    'text': 'natural language processing',
                    'type': 'TECHNOLOGY',
                    'position': [200, 227],
                    'confidence': 0.90,
                    'context': 'Common applications include natural language processing',
                    'properties': {'field': 'Computer Science', 'category': 'AI Application'}
                }
            ]
            
            return entities
        
        mock_llm_optimizer.extract_entities = mock_entity_extraction
        
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.LLMOptimizer') as mock_optimizer_class:
            mock_optimizer_class.return_value = mock_llm_optimizer
            
            # Execute the method
            result = await processor._optimize_for_llm(sample_decomposed_content, sample_ocr_results)
            
            # Verify entity extraction
            entities = result['key_entities']
            assert isinstance(entities, list)
            assert len(entities) >= 3  # Should find multiple entities
            
            # Verify entity structure
            for entity in entities:
                assert 'text' in entity
                assert 'type' in entity
                assert 'position' in entity
                assert 'confidence' in entity
                
                # Verify entity types
                assert entity['type'] in ['TECHNOLOGY', 'PERSON', 'ORGANIZATION', 'CONCEPT', 'LOCATION']
                
                # Verify confidence scores
                assert 0.0 <= entity['confidence'] <= 1.0
                
                # Verify position format
                assert isinstance(entity['position'], list)
                assert len(entity['position']) == 2
                assert entity['position'][0] < entity['position'][1]
            
            # Verify entity integration with chunks
            chunks = result['chunks']
            entity_texts = [e['text'] for e in entities]
            
            # At least some entities should appear in chunks
            found_entities_in_chunks = 0
            for chunk in chunks:
                for entity_text in entity_texts:
                    if entity_text.lower() in chunk['text'].lower():
                        found_entities_in_chunks += 1
                        break
            
            assert found_entities_in_chunks > 0

    @pytest.mark.asyncio
    async def test_optimize_for_llm_content_structuring_and_formatting(self, processor, mock_llm_optimizer):
        """
        GIVEN raw PDF content with various formatting elements
        WHEN _optimize_for_llm structures content
        THEN expect:
            - Content organized for optimal LLM processing
            - Semantic structures identified and preserved
            - Formatting normalized for consistency
            - Document hierarchy maintained
        """
        # Create content with diverse formatting
        formatted_content = {
            'pages': [
                {
                    'page_number': 1,
                    'elements': [
                        {'type': 'heading', 'content': 'Chapter 1: Introduction', 'level': 1, 'bbox': [0, 0, 200, 30]},
                        {'type': 'paragraph', 'content': 'This is the introduction paragraph with important concepts.', 'bbox': [0, 40, 400, 60]},
                        {'type': 'heading', 'content': '1.1 Background', 'level': 2, 'bbox': [0, 80, 150, 100]},
                        {'type': 'list_item', 'content': '• First important point', 'bbox': [20, 120, 300, 140]},
                        {'type': 'list_item', 'content': '• Second important point', 'bbox': [20, 150, 300, 170]},
                        {'type': 'table', 'content': 'Table data here', 'bbox': [0, 200, 400, 300]}
                    ],
                    'text_blocks': [],
                    'images': [],
                    'annotations': []
                }
            ],
            'metadata': {'title': 'Structured Document', 'pages': 1}
        }
        
        ocr_results = {'page_1': {'images': []}}
        
        # Mock content structuring
        def mock_structure_content(content, **kwargs):
            structured_chunks = []
            
            for page in content['pages']:
                current_section = None
                
                for element in page.get('elements', []):
                    if element['type'] == 'heading':
                        # Start new section
                        current_section = {
                            'heading': element['content'],
                            'level': element.get('level', 1),
                            'content': []
                        }
                        
                        structured_chunks.append({
                            'text': element['content'],
                            'metadata': {
                                'type': 'heading',
                                'level': element.get('level', 1),
                                'semantic_role': 'section_title',
                                'page': page['page_number']
                            }
                        })
                    
                    elif element['type'] in ['paragraph', 'list_item']:
                        structured_chunks.append({
                            'text': element['content'],
                            'metadata': {
                                'type': element['type'],
                                'semantic_role': 'content',
                                'section': current_section['heading'] if current_section else None,
                                'page': page['page_number']
                            }
                        })
                    
                    elif element['type'] == 'table':
                        structured_chunks.append({
                            'text': element['content'],
                            'metadata': {
                                'type': 'table',
                                'semantic_role': 'structured_data',
                                'section': current_section['heading'] if current_section else None,
                                'page': page['page_number']
                            }
                        })
            
            return structured_chunks
        
        mock_llm_optimizer.create_chunks = mock_structure_content
        
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.LLMOptimizer') as mock_optimizer_class:
            mock_optimizer_class.return_value = mock_llm_optimizer
            
            # Execute the method
            result = await processor._optimize_for_llm(formatted_content, ocr_results)
            
            # Verify content structuring
            chunks = result['chunks']
            
            # Check for different content types
            headings = [c for c in chunks if c['metadata']['type'] == 'heading']
            paragraphs = [c for c in chunks if c['metadata']['type'] == 'paragraph']
            list_items = [c for c in chunks if c['metadata']['type'] == 'list_item']
            tables = [c for c in chunks if c['metadata']['type'] == 'table']
            
            assert len(headings) >= 2  # Chapter and section headings
            assert len(paragraphs) >= 1  # Introduction paragraph
            assert len(list_items) >= 2  # List items
            assert len(tables) >= 1  # Table content
            
            # Verify semantic roles
            for chunk in chunks:
                assert 'semantic_role' in chunk['metadata']
                assert chunk['metadata']['semantic_role'] in ['section_title', 'content', 'structured_data']
            
            # Verify hierarchy preservation
            for heading in headings:
                assert 'level' in heading['metadata']
                assert heading['metadata']['level'] in [1, 2, 3, 4, 5, 6]
            
            # Verify section association
            content_chunks = [c for c in chunks if c['metadata']['semantic_role'] == 'content']
            for chunk in content_chunks:
                if chunk['metadata'].get('section'):
                    # Should reference a valid heading
                    heading_texts = [h['text'] for h in headings]
                    assert chunk['metadata']['section'] in heading_texts

    @pytest.mark.asyncio
    async def test_optimize_for_llm_chunk_metadata_generation(self, processor, sample_decomposed_content, sample_ocr_results, mock_llm_optimizer):
        """
        GIVEN content being divided into chunks
        WHEN _optimize_for_llm creates chunk metadata
        THEN expect:
            - Each chunk has comprehensive metadata
            - Chunk relationships and positioning preserved
            - Content type and quality indicators included
            - Metadata enables effective retrieval and processing
        """
        # Mock comprehensive metadata generation
        def mock_metadata_chunks(content, **kwargs):
            chunks = []
            chunk_id = 0
            
            for page in content['pages']:
                for i, block in enumerate(page.get('text_blocks', [])):
                    chunks.append({
                        'text': block['content'],
                        'metadata': {
                            'chunk_id': chunk_id,
                            'page': page['page_number'],
                            'position_in_page': i,
                            'content_type': 'text_block',
                            'quality_score': 0.92,
                            'word_count': len(block['content'].split()),
                            'character_count': len(block['content']),
                            'language': 'en',
                            'reading_level': 'college',
                            'sentiment': 'neutral',
                            'topic_scores': {
                                'machine_learning': 0.85,
                                'artificial_intelligence': 0.72,
                                'technology': 0.90
                            },
                            'bbox': block.get('bbox'),
                            'extraction_confidence': 1.0,
                            'processing_timestamp': '2025-01-01T12:00:00Z',
                            'relationships': {
                                'previous_chunk': chunk_id - 1 if chunk_id > 0 else None,
                                'next_chunk': chunk_id + 1,
                                'parent_section': None
                            }
                        }
                    })
                    chunk_id += 1
            
            return chunks
        
        mock_llm_optimizer.create_chunks = mock_metadata_chunks
        
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.LLMOptimizer') as mock_optimizer_class:
            mock_optimizer_class.return_value = mock_llm_optimizer
            
            # Execute the method
            result = await processor._optimize_for_llm(sample_decomposed_content, sample_ocr_results)
            
            # Verify comprehensive metadata
            chunks = result['chunks']
            
            for chunk in chunks:
                metadata = chunk['metadata']
                
                # Verify basic identifiers
                assert 'chunk_id' in metadata
                assert 'page' in metadata
                assert 'position_in_page' in metadata
                
                # Verify content analysis
                assert 'content_type' in metadata
                assert 'quality_score' in metadata
                assert 'word_count' in metadata
                assert 'character_count' in metadata
                
                # Verify quality metrics
                assert 0.0 <= metadata['quality_score'] <= 1.0
                assert metadata['word_count'] > 0
                assert metadata['character_count'] > 0
                
                # Verify language and processing info
                assert 'language' in metadata
                assert 'processing_timestamp' in metadata
                assert 'extraction_confidence' in metadata
                
                # Verify relationships
                assert 'relationships' in metadata
                relationships = metadata['relationships']
                assert 'previous_chunk' in relationships
                assert 'next_chunk' in relationships
                
                # Verify topic analysis if available
                if 'topic_scores' in metadata:
                    topic_scores = metadata['topic_scores']
                    assert isinstance(topic_scores, dict)
                    for topic, score in topic_scores.items():
                        assert 0.0 <= score <= 1.0

    @pytest.mark.asyncio
    async def test_optimize_for_llm_semantic_types_classification(self, processor, mock_llm_optimizer):
        """
        GIVEN diverse content types within document
        WHEN _optimize_for_llm classifies content semantically
        THEN expect:
            - Content types identified (headings, paragraphs, tables, etc.)
            - Semantic roles assigned to content sections
            - Classification supports targeted processing
            - Type information preserved in chunk metadata
        """
        # Create content with diverse semantic types
        diverse_content = {
            'pages': [
                {
                    'page_number': 1,
                    'elements': [
                        {'type': 'title', 'content': 'Research Paper Title', 'font_size': 18},
                        {'type': 'author', 'content': 'John Doe, Jane Smith', 'font_size': 12},
                        {'type': 'abstract', 'content': 'This paper presents novel findings in machine learning.'},
                        {'type': 'heading', 'content': '1. Introduction', 'font_size': 14},
                        {'type': 'paragraph', 'content': 'Machine learning has revolutionized data analysis.'},
                        {'type': 'citation', 'content': '[1] Smith et al. (2024)'},
                        {'type': 'figure_caption', 'content': 'Figure 1: Network architecture diagram'},
                        {'type': 'table_caption', 'content': 'Table 1: Experimental results'},
                        {'type': 'footnote', 'content': 'Additional details available in appendix.'},
                        {'type': 'equation', 'content': 'y = mx + b'},
                        {'type': 'code_block', 'content': 'def train_model(data): return model.fit(data)'}
                    ],
                    'text_blocks': [],
                    'images': [],
                    'annotations': []
                }
            ],
            'metadata': {'title': 'Academic Paper', 'pages': 1}
        }
        
        ocr_results = {'page_1': {'images': []}}
        
        # Mock semantic classification
        def mock_classify_content(content, **kwargs):
            classified_chunks = []
            
            semantic_types_mapping = {
                'title': 'document_title',
                'author': 'authorship_info',
                'abstract': 'summary_content',
                'heading': 'section_header',
                'paragraph': 'body_text',
                'citation': 'reference_material',
                'figure_caption': 'visual_description',
                'table_caption': 'data_description',
                'footnote': 'supplementary_info',
                'equation': 'mathematical_content',
                'code_block': 'executable_content'
            }
            
            for page in content['pages']:
                for element in page.get('elements', []):
                    semantic_types = semantic_types_mapping.get(element['type'], 'unknown')
                    
                    classified_chunks.append({
                        'text': element['content'],
                        'metadata': {
                            'original_type': element['type'],
                            'semantic_types': semantic_types,
                            'semantic_role': self._get_semantic_role(semantic_types),
                            'processing_priority': self._get_processing_priority(semantic_types),
                            'content_category': self._get_content_category(semantic_types),
                            'importance_score': self._get_importance_score(semantic_types),
                            'page': page['page_number']
                        }
                    })
            
            return classified_chunks
        
        def _get_semantic_role(semantic_types):
            role_mapping = {
                'document_title': 'primary_identifier',
                'authorship_info': 'metadata',
                'summary_content': 'overview',
                'section_header': 'structural_marker',
                'body_text': 'primary_content',
                'reference_material': 'citation',
                'visual_description': 'media_annotation',
                'data_description': 'data_annotation',
                'supplementary_info': 'secondary_content',
                'mathematical_content': 'formula',
                'executable_content': 'code'
            }
            return role_mapping.get(semantic_types, 'unclassified')
        
        def _get_processing_priority(semantic_types):
            priority_mapping = {
                'document_title': 'high',
                'summary_content': 'high',
                'section_header': 'high',
                'body_text': 'medium',
                'mathematical_content': 'medium',
                'executable_content': 'medium',
                'authorship_info': 'low',
                'reference_material': 'low',
                'supplementary_info': 'low'
            }
            return priority_mapping.get(semantic_types, 'medium')
        
        def _get_content_category(semantic_types):
            category_mapping = {
                'document_title': 'metadata',
                'authorship_info': 'metadata',
                'summary_content': 'descriptive',
                'section_header': 'structural',
                'body_text': 'narrative',
                'reference_material': 'citation',
                'visual_description': 'descriptive',
                'data_description': 'descriptive',
                'supplementary_info': 'explanatory',
                'mathematical_content': 'technical',
                'executable_content': 'technical'
            }
            return category_mapping.get(semantic_types, 'general')
        
        def _get_importance_score(semantic_types):
            importance_mapping = {
                'document_title': 0.95,
                'summary_content': 0.90,
                'section_header': 0.85,
                'body_text': 0.80,
                'mathematical_content': 0.75,
                'executable_content': 0.75,
                'visual_description': 0.65,
                'data_description': 0.65,
                'authorship_info': 0.60,
                'reference_material': 0.55,
                'supplementary_info': 0.50
            }
            return importance_mapping.get(semantic_types, 0.50)
        
        # Inject helper methods into mock
        mock_classify_content._get_semantic_role = _get_semantic_role
        mock_classify_content._get_processing_priority = _get_processing_priority
        mock_classify_content._get_content_category = _get_content_category
        mock_classify_content._get_importance_score = _get_importance_score
        
        mock_llm_optimizer.create_chunks = mock_classify_content
        
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.LLMOptimizer') as mock_optimizer_class:
            mock_optimizer_class.return_value = mock_llm_optimizer
            
            # Execute the method
            result = await processor._optimize_for_llm(diverse_content, ocr_results)
            
            # Verify semantic classification
            chunks = result['chunks']
            
            # Verify all expected semantic types are present
            semantic_types = set(chunk['metadata']['semantic_types'] for chunk in chunks)
            expected_types = {
                'document_title', 'authorship_info', 'summary_content', 'section_header',
                'body_text', 'reference_material', 'visual_description', 'mathematical_content'
            }
            
            assert len(semantic_types.intersection(expected_types)) >= 5  # At least 5 different types
            
            # Verify semantic roles
            for chunk in chunks:
                metadata = chunk['metadata']
                
                assert 'semantic_types' in metadata
                assert 'semantic_role' in metadata
                assert 'processing_priority' in metadata
                assert 'content_category' in metadata
                assert 'importance_score' in metadata
                
                # Verify semantic role validity
                assert metadata['semantic_role'] in [
                    'primary_identifier', 'metadata', 'overview', 'structural_marker',
                    'primary_content', 'citation', 'media_annotation', 'secondary_content',
                    'formula', 'code', 'unclassified'
                ]
                
                # Verify processing priority
                assert metadata['processing_priority'] in ['high', 'medium', 'low']
                
                # Verify content category
                assert metadata['content_category'] in [
                    'metadata', 'descriptive', 'structural', 'narrative',
                    'citation', 'explanatory', 'technical', 'general'
                ]
                
                # Verify importance score
                assert 0.0 <= metadata['importance_score'] <= 1.0
            
            # Verify high-priority content identified
            high_priority_chunks = [c for c in chunks if c['metadata']['processing_priority'] == 'high']
            assert len(high_priority_chunks) >= 2  # Should have title, headers, etc.

    @pytest.mark.asyncio
    async def test_optimize_for_llm_large_document_memory_management(self, processor, mock_llm_optimizer):
        """
        GIVEN very large document exceeding memory limits
        WHEN _optimize_for_llm processes large content
        THEN expect MemoryError to be raised when limits exceeded
        """
        # Create very large document content
        large_content = {
            'pages': [],
            'metadata': {'title': 'Extremely Large Document', 'pages': 1000}
        }
        
        # Create 1000 pages with substantial content
        for i in range(1000):
            page_content = ' '.join([f'This is sentence {j} on page {i+1}.' for j in range(1000)])  # 1000 sentences per page
            
            large_content['pages'].append({
                'page_number': i + 1,
                'text_blocks': [{'content': page_content}],
                'elements': [],
                'images': [],
                'annotations': []
            })
        
        ocr_results = {f'page_{i+1}': {'images': []} for i in range(1000)}
        
        # Mock memory exhaustion during processing
        def mock_memory_exhaustion(content, **kwargs):
            # Calculate approximate memory usage
            total_text_size = sum(
                len(block['content']) 
                for page in content['pages']
                for block in page.get('text_blocks', [])
            )
            
            # Simulate memory limit (100MB of text)
            if total_text_size > 100 * 1024 * 1024:
                raise MemoryError("Document too large for processing: exceeds memory limits")
            
            return [{'text': 'small content', 'metadata': {}}]
        
        mock_llm_optimizer.create_chunks = mock_memory_exhaustion
        
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.LLMOptimizer') as mock_optimizer_class:
            mock_optimizer_class.return_value = mock_llm_optimizer
            
            # Execute and expect MemoryError
            with pytest.raises(MemoryError, match="Document too large|memory limits|exceeds"):
                await processor._optimize_for_llm(large_content, ocr_results)

    @pytest.mark.asyncio
    async def test_optimize_for_llm_invalid_content_structure(self, processor, mock_llm_optimizer):
        """
        GIVEN invalid or corrupted content structure
        WHEN _optimize_for_llm processes malformed content
        THEN expect ValueError to be raised with content validation details
        """
        invalid_contents = [
            # Missing required fields
            {},
            {'metadata': {}},
            {'pages': []},
            
            # Invalid page structure
            {
                'pages': [{'invalid': 'structure'}],
                'metadata': {}
            },
            
            # Wrong data types
            {
                'pages': 'not_a_list',
                'metadata': {}
            },
            
            # Corrupted page data
            {
                'pages': [
                    {
                        'page_number': 'not_a_number',
                        'text_blocks': 'not_a_list',
                        'elements': None
                    }
                ],
                'metadata': {}
            },
            
            # None values
            None,
            
            # Non-dict structure
            'invalid_string_content'
        ]
        
        ocr_results = {'page_1': {'images': []}}
        
        # Mock validation that detects structure issues
        def mock_validation(content, **kwargs):
            if not isinstance(content, dict):
                raise ValueError("Content must be a dictionary")
            
            if 'pages' not in content:
                raise ValueError("Content missing required 'pages' field")
            
            if not isinstance(content['pages'], list):
                raise ValueError("Pages must be a list")
            
            if 'metadata' not in content:
                raise ValueError("Content missing required 'metadata' field")
            
            for page in content['pages']:
                if not isinstance(page, dict):
                    raise ValueError("Each page must be a dictionary")
                
                if 'page_number' not in page:
                    raise ValueError("Page missing required 'page_number' field")
                
                if not isinstance(page['page_number'], int):
                    raise ValueError("Page number must be an integer")
            
            return [{'text': 'valid', 'metadata': {}}]
        
        mock_llm_optimizer.create_chunks = mock_validation
        
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.LLMOptimizer') as mock_optimizer_class:
            mock_optimizer_class.return_value = mock_llm_optimizer
            
            for invalid_content in invalid_contents:
                with pytest.raises((ValueError, TypeError, AttributeError)):
                    await processor._optimize_for_llm(invalid_content, ocr_results)

    
    
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
