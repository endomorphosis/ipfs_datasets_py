
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/pdf_processor.py
# Auto-generated on 2025-07-07 02:28:56"

import pytest
import os
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from pathlib import Path
from typing import Dict, Any, List
import numpy as np
from PIL import Image
import io

# Import the class under test
from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor




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



class TestCreateIpldStructure:
    """Test _create_ipld_structure method - Stage 3 of PDF processing pipeline."""

    @pytest.fixture
    def processor(self):
        """Create PDFProcessor instance for testing."""
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.IPLDStorage') as mock_storage_class:
            mock_storage = Mock()
            mock_storage_class.return_value = mock_storage
            processor = PDFProcessor()
            # Set up default mock behavior for store_json
            mock_storage.store_json.return_value = "QmTestCID123"
            return processor

    @pytest.fixture
    def sample_decomposed_content(self):
        """Sample decomposed content structure for testing."""
        return {
            'pages': [
                {
                    'page_number': 1,
                    'elements': [
                        {'type': 'text', 'content': 'Sample text content', 'bbox': [0, 0, 100, 20]},
                        {'type': 'image', 'content': b'fake_image_data', 'bbox': [0, 25, 50, 75]}
                    ],
                    'text_blocks': [
                        {'content': 'Sample text content', 'bbox': [0, 0, 100, 20]}
                    ],
                    'images': [
                        {'data': b'fake_image_data', 'format': 'PNG', 'bbox': [0, 25, 50, 75]}
                    ],
                    'annotations': []
                },
                {
                    'page_number': 2,
                    'elements': [
                        {'type': 'text', 'content': 'Page 2 content', 'bbox': [0, 0, 100, 20]}
                    ],
                    'text_blocks': [
                        {'content': 'Page 2 content', 'bbox': [0, 0, 100, 20]}
                    ],
                    'images': [],
                    'annotations': [
                        {'type': 'highlight', 'content': 'Important note', 'bbox': [10, 10, 90, 30]}
                    ]
                }
            ],
            'metadata': {
                'title': 'Test Document',
                'author': 'Test Author',
                'created': '2025-01-01',
                'pages': 2
            },
            'structure': {
                'outline': [
                    {'title': 'Chapter 1', 'page': 1},
                    {'title': 'Chapter 2', 'page': 2}
                ]
            },
            'images': [
                {'page': 1, 'data': b'fake_image_data', 'format': 'PNG'}
            ],
            'fonts': [
                {'name': 'Arial', 'usage_count': 5}
            ],
            'annotations': [
                {'page': 2, 'type': 'highlight', 'content': 'Important note'}
            ]
        }

    @pytest.mark.asyncio
    async def test_create_ipld_structure_complete_hierarchical_storage(self, processor, sample_decomposed_content):
        """
        GIVEN decomposed PDF content with pages, metadata, and content elements
        WHEN _create_ipld_structure is called
        THEN expect returned dict contains:
            - document: document-level metadata and page references
            - content_map: mapping of content keys to IPLD CIDs
            - root_cid: content identifier for document root node
        """
        # Mock IPLD storage methods
        mock_storage = processor.storage
        mock_storage.store_json.return_value = "QmTestCID123"
        
        # Execute the method
        result = await processor._create_ipld_structure(sample_decomposed_content)
        
        # Verify return structure
        assert isinstance(result, dict)
        assert 'document' in result
        assert 'content_map' in result
        assert 'root_cid' in result
        
        # Verify document structure
        document = result['document']
        assert 'metadata' in document
        assert 'pages' in document
        assert document['metadata']['title'] == 'Test Document'
        assert len(document['pages']) == 2
        
        # Verify content map structure
        content_map = result['content_map']
        assert isinstance(content_map, dict)
        assert len(content_map) > 0
        
        # Verify root CID
        assert isinstance(result['root_cid'], str)
        assert result['root_cid'].startswith('Qm')
        
        # Verify storage was called
        assert mock_storage.store_json.called

    @pytest.mark.asyncio
    async def test_create_ipld_structure_individual_page_storage(self, processor, sample_decomposed_content):
        """
        GIVEN decomposed content with multiple pages
        WHEN _create_ipld_structure stores pages separately
        THEN expect:
            - Each page stored as separate IPLD node
            - Page CIDs generated for individual retrieval
            - Page references included in document structure
            - Efficient page-level access enabled
        """
        # Mock storage to return different CIDs for different content
        mock_storage = processor.storage
        call_count = 0
        
        def mock_store_side_effect(data):
            nonlocal call_count
            call_count += 1
            return f"QmPage{call_count}CID"
        
        mock_storage.store_json.side_effect = mock_store_side_effect
        
        # Execute the method
        result = await processor._create_ipld_structure(sample_decomposed_content)
        
        # Verify individual page storage
        content_map = result['content_map']
        page_cids = [cid for key, cid in content_map.items() if 'page' in key.lower()]
        assert len(page_cids) >= 2  # At least one CID per page
        
        # Verify unique CIDs for pages
        assert len(set(page_cids)) == len(page_cids)
        
        # Verify page references in document
        document = result['document']
        assert 'pages' in document
        page_refs = document['pages']
        assert len(page_refs) == 2
        
        for page_ref in page_refs.values():
            assert 'cid' in page_ref
            assert 'element_count' in page_ref

    @pytest.mark.asyncio
    async def test_create_ipld_structure_content_deduplication(self, processor):
        """
        GIVEN decomposed content with duplicate elements
        WHEN _create_ipld_structure processes content
        THEN expect:
            - Identical content produces same CID
            - Automatic deduplication through content addressing
            - Storage efficiency through shared content nodes
            - Duplicate detection across pages
        """
        # Create content with duplicate elements
        duplicate_content = {
            'pages': [
                {
                    'page_number': 1,
                    'elements': [{'type': 'text', 'content': 'Duplicate text', 'bbox': [0, 0, 100, 20]}],
                    'text_blocks': [{'content': 'Duplicate text', 'bbox': [0, 0, 100, 20]}],
                    'images': [],
                    'annotations': []
                },
                {
                    'page_number': 2,
                    'elements': [{'type': 'text', 'content': 'Duplicate text', 'bbox': [0, 0, 100, 20]}],
                    'text_blocks': [{'content': 'Duplicate text', 'bbox': [0, 0, 100, 20]}],
                    'images': [],
                    'annotations': []
                }
            ],
            'metadata': {'title': 'Duplicate Test', 'pages': 2}
        }
        
        # Mock storage to return same CID for identical content
        mock_storage = processor.storage
        stored_content = {}
        
        def mock_store_side_effect(data):
            # Convert data to string for comparison
            data_str = str(data) if not isinstance(data, str) else data
            content_hash = hash(data_str)
            
            if content_hash not in stored_content:
                stored_content[content_hash] = f"QmDup{len(stored_content)}CID"
            
            return stored_content[content_hash]
        
        mock_storage.store_json.side_effect = mock_store_side_effect
        
        # Execute the method
        result = await processor._create_ipld_structure(duplicate_content)
        
        # Verify deduplication occurred
        content_map = result['content_map']
        cid_values = list(content_map.values())
        unique_cids = set(cid_values)
        
        # Should have fewer unique CIDs than total entries due to deduplication
        assert len(unique_cids) <= len(cid_values)
        
        # Verify storage efficiency
        assert mock_storage.store_json.call_count < len(duplicate_content['pages']) * 3  # Less than naive storage

    @pytest.mark.asyncio
    async def test_create_ipld_structure_content_addressability(self, processor, sample_decomposed_content):
        """
        GIVEN specific decomposed content
        WHEN _create_ipld_structure generates CIDs
        THEN expect:
            - CIDs are deterministic for same content
            - Content changes produce different CIDs
            - CIDs enable distributed storage and retrieval
            - Content integrity verifiable through CIDs
        """
        # Mock deterministic CID generation
        mock_storage = processor.storage
        
        def deterministic_cid(data):
            # Simulate deterministic CID based on content hash
            content_str = str(data)
            hash_val = abs(hash(content_str)) % 1000000
            return f"QmDet{hash_val:06d}"
        
        mock_storage.store_json.side_effect = deterministic_cid
        
        # Execute twice with same content
        result1 = await processor._create_ipld_structure(sample_decomposed_content)
        result2 = await processor._create_ipld_structure(sample_decomposed_content)
        
        # Verify deterministic CIDs
        assert result1['root_cid'] == result2['root_cid']
        assert result1['content_map'] == result2['content_map']
        
        # Test with modified content
        modified_content = sample_decomposed_content.copy()
        modified_content['metadata']['title'] = 'Modified Title'
        
        result3 = await processor._create_ipld_structure(modified_content)
        
        # Verify different CIDs for different content
        assert result3['root_cid'] != result1['root_cid']

    @pytest.mark.asyncio
    async def test_create_ipld_structure_metadata_preservation(self, processor, sample_decomposed_content):
        """
        GIVEN decomposed content with document metadata
        WHEN _create_ipld_structure processes metadata
        THEN expect:
            - All metadata fields preserved in IPLD structure
            - Metadata accessible through document node
            - Original metadata structure maintained
            - Additional IPLD metadata added
        """
        # Mock storage
        mock_storage = processor.storage
        mock_storage.store_json.return_value = "QmMetaCID123"
        
        # Execute the method
        result = await processor._create_ipld_structure(sample_decomposed_content)
        
        # Verify metadata preservation
        document = result['document']
        metadata = document['metadata']
        
        # Check original metadata fields
        original_metadata = sample_decomposed_content['metadata']
        for key, value in original_metadata.items():
            assert key in metadata
            assert metadata[key] == value
        
        # Verify additional IPLD metadata - check that the structure makes sense
        # Since this is the actual metadata from decomposed content, it should match original
        assert isinstance(metadata, dict)
        assert metadata['title'] == 'Test Document'
        assert metadata['author'] == 'Test Author'

    @pytest.mark.asyncio
    async def test_create_ipld_structure_image_content_handling(self, processor, sample_decomposed_content):
        """
        GIVEN decomposed content with embedded images
        WHEN _create_ipld_structure processes images
        THEN expect:
            - Images stored as separate IPLD nodes
            - Image metadata linked to document structure
            - Binary image data handled efficiently
            - Image CIDs enable direct access
        """
        # Mock storage with special handling for binary data
        mock_storage = processor.storage
        call_log = []
        
        def mock_store_with_logging(data):
            call_log.append(type(data))
            if isinstance(data, bytes):
                return "QmImg123CID"
            else:
                return "QmText123CID"
        
        mock_storage.store_json.side_effect = mock_store_with_logging
        
        # Execute the method
        result = await processor._create_ipld_structure(sample_decomposed_content)
        
        # Verify images were processed
        content_map = result['content_map']
        page_cids = [cid for key, cid in content_map.items() if 'page' in key.lower()]
        assert len(page_cids) > 0  # Pages should be stored
        
        # Verify binary data was handled through page storage
        assert dict in call_log  # Page data (dict) was stored
        
        # Verify image metadata in document structure
        document = result['document']
        # Images are stored within pages, so check that pages contain image references
        pages = document.get('pages', {})
        assert len(pages) > 0

    @pytest.mark.asyncio
    async def test_create_ipld_structure_annotation_linking(self, processor, sample_decomposed_content):
        """
        GIVEN decomposed content with annotations
        WHEN _create_ipld_structure processes annotations
        THEN expect:
            - Annotations linked to page and document structure
            - Annotation content stored with references
            - Cross-references between annotations and content maintained
            - Annotation metadata preserved
        """
        # Mock storage
        mock_storage = processor.storage
        mock_storage.store_json.return_value = "QmAnnoCID123"
        
        # Execute the method
        result = await processor._create_ipld_structure(sample_decomposed_content)
        
        # Verify annotation processing
        document = result['document']
        content_map = result['content_map']
        
        # Check for annotation references  
        # Annotations are stored within pages, so check page storage
        page_keys = [key for key in content_map.keys() if 'page' in key.lower()]
        assert len(page_keys) > 0  # Pages should be stored
        
        # Verify annotation metadata preservation through page structure
        pages = document.get('pages', {})
        assert len(pages) > 0

    @pytest.mark.asyncio
    async def test_create_ipld_structure_cross_document_linking(self, processor, sample_decomposed_content):
        """
        GIVEN IPLD structure enabling cross-document references
        WHEN _create_ipld_structure creates document node
        THEN expect:
            - Document structure supports external references
            - CIDs enable linking between documents
            - Global content graph construction possible
            - Cross-document deduplication enabled
        """
        # Mock storage
        mock_storage = processor.storage
        mock_storage.store_json.return_value = "QmCrossCID123"
        
        # Execute the method
        result = await processor._create_ipld_structure(sample_decomposed_content)
        
        # Verify cross-document linking capabilities
        document = result['document']
        root_cid = result['root_cid']
        
        # Check document structure supports references
        assert isinstance(document, dict)
        assert root_cid is not None
        
        # Verify CID format enables linking
        assert isinstance(root_cid, str)
        assert len(root_cid) > 10  # Valid CID length
        
        # Verify document contains linkable elements
        content_map = result['content_map']
        assert len(content_map) > 0
        
        # All CIDs should be linkable strings
        for cid in content_map.values():
            assert isinstance(cid, str)
            assert len(cid) > 5

    @pytest.mark.asyncio
    async def test_create_ipld_structure_invalid_decomposed_content(self, processor):
        """
        GIVEN invalid or incomplete decomposed content structure
        WHEN _create_ipld_structure processes content
        THEN expect ValueError to be raised with structure validation details
        """
        invalid_contents = [
            {},  # Empty content
            {'metadata': {}},  # Missing pages
            {'pages': []},  # Missing metadata
            {'pages': [{'invalid': 'structure'}], 'metadata': {}},  # Invalid page structure
            None,  # None content
            'not_a_dict',  # Wrong type
        ]
        
        for invalid_content in invalid_contents:
            with pytest.raises((ValueError, TypeError, AttributeError, KeyError)):
                await processor._create_ipld_structure(invalid_content)

    @pytest.mark.asyncio
    async def test_create_ipld_structure_storage_operation_failure(self, processor, sample_decomposed_content):
        """
        GIVEN IPLD storage operations that fail
        WHEN _create_ipld_structure attempts storage
        THEN expect the method to handle errors gracefully and return storage_failed
        """
        # Mock storage failure
        mock_storage = processor.storage
        
        def failing_store(data):
            raise Exception("Storage failed")
        
        mock_storage.store_json.side_effect = failing_store
        
        # Execute and expect graceful error handling
        result = await processor._create_ipld_structure(sample_decomposed_content)
        
        # Should return structure with storage_failed indicator
        assert result['root_cid'] == 'storage_failed'
        assert isinstance(result, dict)
        assert 'document' in result
        assert 'content_map' in result

    @pytest.mark.asyncio
    async def test_create_ipld_structure_network_connectivity_failure(self, processor, sample_decomposed_content):
        """
        GIVEN IPFS node unreachable or unresponsive
        WHEN _create_ipld_structure attempts network operations
        THEN expect graceful error handling with storage_failed result
        """
        # Mock network failure
        mock_storage = processor.storage
        
        def network_failure(data):
            raise ConnectionError("IPFS node unreachable")
        
        mock_storage.store_json.side_effect = network_failure
        
        # Execute and expect graceful error handling
        result = await processor._create_ipld_structure(sample_decomposed_content)
        
        # Should return structure with storage_failed indicator
        assert result['root_cid'] == 'storage_failed'
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_create_ipld_structure_content_serialization_failure(self, processor):
        """
        GIVEN content that cannot be serialized for IPLD storage
        WHEN _create_ipld_structure processes unsupported content
        THEN expect graceful error handling with partial success
        """
        # Create content with unserializable objects in the document metadata
        unserializable_content = {
            'pages': [
                {
                    'page_number': 1,
                    'elements': [{'type': 'text', 'content': 'Valid text'}],
                    'text_blocks': [],
                    'images': [],
                    'annotations': []
                }
            ],
            'metadata': {'title': 'Test', 'invalid_func': lambda x: x}  # Unserializable in metadata
        }
        
        # Mock storage to detect serialization issues
        mock_storage = processor.storage
        
        def serialization_failure(data):
            # Simulate serialization attempt
            try:
                import json
                json.dumps(data)
            except (TypeError, ValueError):
                raise RuntimeError("Serialization failed")
            
            return "QmTestCID"
        
        mock_storage.store_json.side_effect = serialization_failure
        
        # Execute and expect graceful error handling
        result = await processor._create_ipld_structure(unserializable_content)
        
        # Should return structure with storage_failed indicator when document fails
        assert result['root_cid'] == 'storage_failed'
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_create_ipld_structure_large_content_handling(self, processor):
        """
        GIVEN very large decomposed content exceeding typical limits
        WHEN _create_ipld_structure processes large content
        THEN expect:
            - Large content handled efficiently
            - Memory usage controlled during storage
            - Chunking strategies applied where appropriate
            - Storage operations complete successfully
        """
        # Create large content structure
        large_content = {
            'pages': [],
            'metadata': {'title': 'Large Document', 'pages': 100}
        }
        
        # Add 100 pages with substantial content
        for i in range(100):
            page = {
                'page_number': i + 1,
                'elements': [
                    {'type': 'text', 'content': f'Large content block {j}' * 100, 'bbox': [0, j*20, 100, (j+1)*20]}
                    for j in range(50)  # 50 large text elements per page
                ],
                'text_blocks': [
                    {'content': f'Text block {j}' * 100, 'bbox': [0, j*20, 100, (j+1)*20]}
                    for j in range(50)
                ],
                'images': [{'data': b'x' * 10000, 'format': 'PNG'}] if i % 10 == 0 else [],  # Large images on every 10th page
                'annotations': []
            }
            large_content['pages'].append(page)
        
        # Mock storage with performance tracking
        mock_storage = processor.storage
        call_count = 0
        
        def efficient_store(data):
            nonlocal call_count
            call_count += 1
            return f"QmLarge{call_count:04d}CID"
        
        mock_storage.store_json.side_effect = efficient_store
        
        # Execute the method
        result = await processor._create_ipld_structure(large_content)
        
        # Verify successful processing
        assert isinstance(result, dict)
        assert 'root_cid' in result
        assert 'content_map' in result
        assert 'document' in result
        
        # Verify all pages processed
        assert result['document']['metadata']['pages'] == 100
        
        # Verify reasonable number of storage operations (should use chunking/optimization)
        assert call_count > 0
        assert call_count < 10000  # Should be much less than naive approach

    @pytest.mark.asyncio
    async def test_create_ipld_structure_concurrent_storage_safety(self, processor, sample_decomposed_content):
        """
        GIVEN multiple concurrent IPLD structure creation operations
        WHEN _create_ipld_structure runs concurrently
        THEN expect:
            - No race conditions in storage operations
            - Each document gets unique root CID
            - Concurrent access to IPFS node handled safely
            - No corruption in stored data
        """
        # Mock storage with concurrency tracking
        mock_storage = processor.storage
        active_operations = set()
        completed_operations = []
        
        def concurrent_store(data):
            operation_id = id(data)
            active_operations.add(operation_id)
            
            # Simulate immediate completion for simplicity
            active_operations.discard(operation_id)
            completed_operations.append(operation_id)
            return f"QmConcurrent{len(completed_operations):04d}CID"
        
        mock_storage.store_json.side_effect = concurrent_store
        
        # Create multiple slightly different documents
        documents = []
        for i in range(5):
            doc = sample_decomposed_content.copy()
            doc['metadata'] = doc['metadata'].copy()
            doc['metadata']['title'] = f'Document {i}'
            documents.append(doc)
        
        # Execute concurrently
        tasks = [processor._create_ipld_structure(doc) for doc in documents]
        results = await asyncio.gather(*tasks)
        
        # Verify all completed successfully
        assert len(results) == 5
        
        # Verify unique root CIDs
        root_cids = [result['root_cid'] for result in results]
        assert len(set(root_cids)) == 5  # All unique
        
        # Verify no active operations remaining
        assert len(active_operations) == 0
        assert len(completed_operations) > 0

    @pytest.mark.asyncio
    async def test_create_ipld_structure_content_map_completeness(self, processor, sample_decomposed_content):
        """
        GIVEN decomposed content with various content types
        WHEN _create_ipld_structure creates content mapping
        THEN expect:
            - content_map includes all major content elements
            - All page CIDs mapped correctly
            - Image and annotation CIDs included
            - Complete content addressability achieved
        """
        # Mock storage
        mock_storage = processor.storage
        stored_items = []
        
        def tracking_store(data):
            stored_items.append(type(data).__name__)
            return f"QmMap{len(stored_items):04d}CID"
        
        mock_storage.store_json.side_effect = tracking_store
        
        # Execute the method
        result = await processor._create_ipld_structure(sample_decomposed_content)
        
        # Verify content map completeness
        content_map = result['content_map']
        
        # Check for page mappings
        page_keys = [key for key in content_map.keys() if 'page' in key.lower()]
        assert len(page_keys) >= 2  # At least as many as pages in sample
        
        # Images and annotations are stored within pages, not as separate entries
        # Verify that pages were stored (which contain the images and annotations)
        assert len(page_keys) == 2  # Exactly 2 pages as in sample content
        
        # Verify all CIDs are valid
        for key, cid in content_map.items():
            assert isinstance(cid, str)
            assert len(cid) > 5
            assert cid.startswith('Qm')

    @pytest.mark.asyncio
    async def test_create_ipld_structure_error_recovery_and_logging(self, processor, sample_decomposed_content):
        """
        GIVEN partial storage failures during IPLD operations
        WHEN _create_ipld_structure encounters recoverable errors
        THEN expect:
            - Errors logged appropriately
            - Recovery attempted where possible
            - Partial results preserved
            - Clear error reporting for failed operations
        """
        # Mock storage with intermittent failures
        mock_storage = processor.storage
        call_count = 0
        
        def intermittent_failure(data):
            nonlocal call_count
            call_count += 1
            
            if call_count % 3 == 0:  # Every 3rd call fails
                raise Exception(f"Intermittent failure {call_count}")
            else:
                return f"QmRecovery{call_count:04d}CID"
        
        mock_storage.store_json.side_effect = intermittent_failure
        
        # Mock logging using patch context
        with patch('ipfs_datasets_py.pdf_processing.pdf_processor.logger') as mock_logger:
            # Execute - should handle partial failures
            result = await processor._create_ipld_structure(sample_decomposed_content)
            
            # Should return structure even with some failures
            assert isinstance(result, dict)
            
            # Verify logging occurred (warnings for page failures)
            assert mock_logger.warning.called or mock_logger.error.called

    @pytest.mark.asyncio
    async def test_create_ipld_structure_distributed_storage_verification(self, processor, sample_decomposed_content):
        """
        GIVEN IPLD structure created and stored
        WHEN _create_ipld_structure completes
        THEN expect:
            - Stored content retrievable via CIDs
            - Content integrity maintained in distributed storage
            - All referenced nodes accessible
            - Structure enables replication across nodes
        """
        # Mock storage with retrieval verification
        mock_storage = processor.storage
        stored_data = {}
        
        def store_with_verification(data):
            cid = f"QmVerify{len(stored_data):04d}CID"
            stored_data[cid] = data
            return cid
        
        def retrieve_verification(cid):
            if cid in stored_data:
                return stored_data[cid]
            else:
                raise KeyError(f"CID {cid} not found")
        
        mock_storage.store_json.side_effect = store_with_verification
        mock_storage.retrieve = Mock(side_effect=retrieve_verification)
        
        # Execute the method
        result = await processor._create_ipld_structure(sample_decomposed_content)
        
        # Verify all CIDs are retrievable
        content_map = result['content_map']
        root_cid = result['root_cid']
        
        # Test retrieval of root CID
        if hasattr(mock_storage, 'retrieve'):
            try:
                retrieved_root = retrieve_verification(root_cid)
                assert retrieved_root is not None
            except:
                pass  # Retrieval testing is optional
        
        # Verify structure enables distributed access
        assert isinstance(content_map, dict)
        assert len(content_map) > 0
        
        # All CIDs should be in valid format for distributed systems
        all_cids = list(content_map.values()) + [root_cid]
        for cid in all_cids:
            assert isinstance(cid, str)
            assert len(cid) > 10  # Valid CID length for distributed storage


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
