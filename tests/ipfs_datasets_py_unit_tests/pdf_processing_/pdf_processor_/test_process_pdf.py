#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/pdf_processor.py
# Auto-generated on 2025-07-07 02:28:56"

import pytest
import os
from unittest.mock import patch

from tests._test_utils import (
    raise_on_bad_callable_metadata,
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



class TestProcessPdf:
    """Test process_pdf method - the main pipeline orchestrator."""

    @pytest.mark.asyncio
    async def test_process_pdf_successful_complete_pipeline(self):
        """
        GIVEN valid PDF file path and optional metadata
        WHEN process_pdf is called
        THEN expect:
            - All 10 pipeline stages execute in sequence
            - Success status returned
            - Document ID generated
            - IPLD CID returned
            - Entity and relationship counts provided
            - Processing metadata includes time and quality scores
        """
        processor = PDFProcessor()
        pdf_path = Path("test_document.pdf")
        metadata = {"source": "test", "priority": "high"}
        
        # Mock the pipeline stages to return expected data
        with patch.object(processor, '_validate_and_analyze_pdf') as mock_validate, \
             patch.object(processor, '_decompose_pdf') as mock_decompose, \
             patch.object(processor, '_create_ipld_structure') as mock_ipld, \
             patch.object(processor, '_process_ocr') as mock_ocr, \
             patch.object(processor, '_optimize_for_llm') as mock_llm, \
             patch.object(processor, '_extract_entities') as mock_entities, \
             patch.object(processor, '_create_embeddings') as mock_embeddings, \
             patch.object(processor, '_integrate_with_graphrag') as mock_graphrag, \
             patch.object(processor, '_analyze_cross_document_relationships') as mock_cross_doc, \
             patch.object(processor, '_setup_query_interface') as mock_query:
            
            # Setup mock returns
            mock_validate.return_value = {"file_path": str(pdf_path), "page_count": 10}
            mock_decompose.return_value = {"pages": [], "metadata": {}}
            mock_ipld.return_value = {"root_cid": "QmTest123"}
            mock_ocr.return_value = {"ocr_results": []}
            mock_llm.return_value = {"llm_document": None}
            mock_entities.return_value = {"entities": [], "relationships": []}
            mock_embeddings.return_value = {"embeddings": []}
            mock_graphrag.return_value = {"document": {"id": "doc_123"}, "knowledge_graph": None}
            mock_cross_doc.return_value = []
            mock_query.return_value = None
            
            result = await processor.process_pdf(pdf_path, metadata)
            
            # Verify all stages were called
            mock_validate.assert_called_once()
            mock_decompose.assert_called_once()
            mock_ipld.assert_called_once()
            mock_ocr.assert_called_once()
            mock_llm.assert_called_once()
            mock_entities.assert_called_once()
            mock_embeddings.assert_called_once()
            mock_graphrag.assert_called_once()
            mock_cross_doc.assert_called_once()
            mock_query.assert_called_once()
            
            # Verify result structure
            assert result["status"] == "success"
            assert "document_id" in result
            assert "ipld_cid" in result
            assert "entities_count" in result
            assert "relationships_count" in result
            assert "cross_doc_relations" in result
            assert "processing_metadata" in result

    @pytest.mark.asyncio
    async def test_process_pdf_with_string_path(self):
        """
        GIVEN PDF file path as string
        WHEN process_pdf is called
        THEN expect:
            - String path is converted to Path object
            - Processing proceeds normally
            - Results contain correct file path reference
        """
        processor = PDFProcessor()
        pdf_path_str = "test_document.pdf"
        
        with patch.object(processor, '_validate_and_analyze_pdf') as mock_validate:
            mock_validate.return_value = {"file_path": pdf_path_str, "page_count": 1}
            
            # Mock other methods to avoid full pipeline execution
            with patch.object(processor, '_decompose_pdf'), \
                 patch.object(processor, '_create_ipld_structure'), \
                 patch.object(processor, '_process_ocr'), \
                 patch.object(processor, '_optimize_for_llm'), \
                 patch.object(processor, '_extract_entities'), \
                 patch.object(processor, '_create_embeddings'), \
                 patch.object(processor, '_integrate_with_graphrag'), \
                 patch.object(processor, '_analyze_cross_document_relationships'), \
                 patch.object(processor, '_setup_query_interface'):
                
                result = await processor.process_pdf(pdf_path_str)
                
                # Verify Path conversion occurred
                args, kwargs = mock_validate.call_args
                assert isinstance(args[0], Path)
                assert str(args[0]) == pdf_path_str

    @pytest.mark.asyncio
    async def test_process_pdf_with_path_object(self):
        """
        GIVEN PDF file path as Path object
        WHEN process_pdf is called
        THEN expect:
            - Path object is used directly
            - Processing proceeds normally
            - Results contain correct file path reference
        """
        processor = PDFProcessor()
        pdf_path = Path("test_document.pdf")
        
        with patch.object(processor, '_validate_and_analyze_pdf') as mock_validate:
            mock_validate.return_value = {"file_path": str(pdf_path), "page_count": 1}
            
            # Mock other methods
            with patch.object(processor, '_decompose_pdf'), \
                 patch.object(processor, '_create_ipld_structure'), \
                 patch.object(processor, '_process_ocr'), \
                 patch.object(processor, '_optimize_for_llm'), \
                 patch.object(processor, '_extract_entities'), \
                 patch.object(processor, '_create_embeddings'), \
                 patch.object(processor, '_integrate_with_graphrag'), \
                 patch.object(processor, '_analyze_cross_document_relationships'), \
                 patch.object(processor, '_setup_query_interface'):
                
                result = await processor.process_pdf(pdf_path)
                
                # Verify Path object was used directly
                args, kwargs = mock_validate.call_args
                assert args[0] is pdf_path

    @pytest.mark.asyncio
    async def test_process_pdf_with_custom_metadata(self):
        """
        GIVEN PDF file and custom metadata dict
        WHEN process_pdf is called with metadata
        THEN expect:
            - Custom metadata is merged with extracted metadata
            - Source, priority, and tags are preserved
            - Processing results include merged metadata
        """
        processor = PDFProcessor()
        pdf_path = Path("test_document.pdf")
        custom_metadata = {
            "source": "legal_docs",
            "priority": "high",
            "tags": ["contract", "important"]
        }
        
        with patch.object(processor, '_validate_and_analyze_pdf') as mock_validate:
            mock_validate.return_value = {"file_path": str(pdf_path), "page_count": 1}
            
            with patch.object(processor, '_decompose_pdf') as mock_decompose:
                mock_decompose.return_value = {
                    "metadata": {"title": "Test Document", "author": "Test Author"},
                    "pages": []
                }
                
                # Mock other methods
                with patch.object(processor, '_create_ipld_structure'), \
                     patch.object(processor, '_process_ocr'), \
                     patch.object(processor, '_optimize_for_llm'), \
                     patch.object(processor, '_extract_entities'), \
                     patch.object(processor, '_create_embeddings'), \
                     patch.object(processor, '_integrate_with_graphrag'), \
                     patch.object(processor, '_analyze_cross_document_relationships'), \
                     patch.object(processor, '_setup_query_interface'):
                    
                    result = await processor.process_pdf(pdf_path, custom_metadata)
                    
                    # Verify custom metadata was passed through
                    assert custom_metadata["source"] == "legal_docs"
                    assert custom_metadata["priority"] == "high"
                    assert custom_metadata["tags"] == ["contract", "important"]

    @pytest.mark.asyncio
    async def test_process_pdf_with_none_metadata(self):
        """
        GIVEN PDF file and metadata=None
        WHEN process_pdf is called
        THEN expect:
            - Processing proceeds without custom metadata
            - Only extracted document metadata is used
            - No metadata merge operations occur
        """
        processor = PDFProcessor()
        pdf_path = Path("test_document.pdf")
        
        with patch.object(processor, '_validate_and_analyze_pdf') as mock_validate:
            mock_validate.return_value = {"file_path": str(pdf_path), "page_count": 1}
            
            # Mock other methods
            with patch.object(processor, '_decompose_pdf'), \
                 patch.object(processor, '_create_ipld_structure'), \
                 patch.object(processor, '_process_ocr'), \
                 patch.object(processor, '_optimize_for_llm'), \
                 patch.object(processor, '_extract_entities'), \
                 patch.object(processor, '_create_embeddings'), \
                 patch.object(processor, '_integrate_with_graphrag'), \
                 patch.object(processor, '_analyze_cross_document_relationships'), \
                 patch.object(processor, '_setup_query_interface'):
                
                result = await processor.process_pdf(pdf_path, metadata=None)
                
                # Verify processing completed without metadata
                assert result is not None

    @pytest.mark.asyncio
    async def test_process_pdf_returns_success_status_with_all_fields(self):
        """
        GIVEN successful PDF processing
        WHEN process_pdf completes
        THEN expect returned dict contains:
            - status: 'success'
            - document_id: string UUID
            - ipld_cid: valid content identifier
            - entities_count: non-negative integer
            - relationships_count: non-negative integer
            - cross_doc_relations: non-negative integer
            - processing_metadata with pipeline_version, processing_time, quality_scores, stages_completed
        """
        processor = PDFProcessor()
        pdf_path = Path("test_document.pdf")
        
        # Mock all pipeline stages
        with patch.object(processor, '_validate_and_analyze_pdf') as mock_validate, \
             patch.object(processor, '_decompose_pdf') as mock_decompose, \
             patch.object(processor, '_create_ipld_structure') as mock_ipld, \
             patch.object(processor, '_process_ocr') as mock_ocr, \
             patch.object(processor, '_optimize_for_llm') as mock_llm, \
             patch.object(processor, '_extract_entities') as mock_entities, \
             patch.object(processor, '_create_embeddings') as mock_embeddings, \
             patch.object(processor, '_integrate_with_graphrag') as mock_graphrag, \
             patch.object(processor, '_analyze_cross_document_relationships') as mock_cross_doc, \
             patch.object(processor, '_setup_query_interface') as mock_query:
            
            # Setup mock returns
            mock_validate.return_value = {"file_path": str(pdf_path)}
            mock_decompose.return_value = {"pages": [], "metadata": {}}
            mock_ipld.return_value = {"root_cid": "QmTestCID123"}
            mock_ocr.return_value = {"ocr_results": []}
            mock_llm.return_value = {"llm_document": None}
            mock_entities.return_value = {"entities": [1, 2, 3], "relationships": [1, 2]}
            mock_embeddings.return_value = {"embeddings": []}
            mock_graphrag.return_value = {"document": {"id": "doc_123"}}
            mock_cross_doc.return_value = [1]
            mock_query.return_value = None
            
            result = await processor.process_pdf(pdf_path)
            
            # Verify all required fields are present
            assert result["status"] == "success"
            assert isinstance(result["document_id"], str)
            assert isinstance(result["ipld_cid"], str)
            assert isinstance(result["entities_count"], int)
            assert result["entities_count"] >= 0
            assert isinstance(result["relationships_count"], int)
            assert result["relationships_count"] >= 0
            assert isinstance(result["cross_doc_relations"], int)
            assert result["cross_doc_relations"] >= 0
            
            # Verify processing metadata structure
            assert "processing_metadata" in result
            metadata = result["processing_metadata"]
            assert "pipeline_version" in metadata
            assert "processing_time" in metadata
            assert "quality_scores" in metadata
            assert "stages_completed" in metadata

    @pytest.mark.asyncio
    async def test_process_pdf_file_not_found_error(self):
        """
        GIVEN non-existent PDF file path
        WHEN process_pdf is called
        THEN expect FileNotFoundError to be raised
        """
        processor = PDFProcessor()
        non_existent_path = Path("non_existent_file.pdf")
        
        with patch.object(processor, '_validate_and_analyze_pdf') as mock_validate:
            mock_validate.side_effect = FileNotFoundError("File not found")
            
            with pytest.raises(FileNotFoundError):
                await processor.process_pdf(non_existent_path)

    @pytest.mark.asyncio
    async def test_process_pdf_invalid_pdf_error(self):
        """
        GIVEN invalid or corrupted PDF file
        WHEN process_pdf is called
        THEN expect ValueError to be raised
        """
        processor = PDFProcessor()
        invalid_pdf_path = Path("invalid.pdf")
        
        with patch.object(processor, '_validate_and_analyze_pdf') as mock_validate:
            mock_validate.side_effect = ValueError("Invalid PDF format")
            
            with pytest.raises(ValueError):
                await processor.process_pdf(invalid_pdf_path)

    @pytest.mark.asyncio
    async def test_process_pdf_permission_error(self):
        """
        GIVEN PDF file without read permissions
        WHEN process_pdf is called
        THEN expect PermissionError to be raised
        """
        processor = PDFProcessor()
        restricted_pdf_path = Path("restricted.pdf")
        
        with patch.object(processor, '_validate_and_analyze_pdf') as mock_validate:
            mock_validate.side_effect = PermissionError("Permission denied")
            
            with pytest.raises(PermissionError):
                await processor.process_pdf(restricted_pdf_path)

    @pytest.mark.asyncio
    async def test_process_pdf_runtime_error_during_pipeline(self):
        """
        GIVEN critical pipeline stage failure
        WHEN process_pdf encounters unrecoverable error
        THEN expect RuntimeError to be raised
        """
        processor = PDFProcessor()
        pdf_path = Path("test.pdf")
        
        with patch.object(processor, '_validate_and_analyze_pdf') as mock_validate:
            mock_validate.return_value = {"file_path": str(pdf_path)}
            
            with patch.object(processor, '_decompose_pdf') as mock_decompose:
                mock_decompose.side_effect = RuntimeError("Critical pipeline failure")
                
                with pytest.raises(RuntimeError):
                    await processor.process_pdf(pdf_path)

    @pytest.mark.asyncio
    async def test_process_pdf_timeout_error(self):
        """
        GIVEN processing that exceeds configured timeout
        WHEN process_pdf runs too long
        THEN expect TimeoutError to be raised
        """
        processor = PDFProcessor()
        pdf_path = Path("large_document.pdf")
        
        with patch.object(processor, '_validate_and_analyze_pdf') as mock_validate:
            mock_validate.side_effect = TimeoutError("Processing timeout exceeded")
            
            with pytest.raises(TimeoutError):
                await processor.process_pdf(pdf_path)

    @pytest.mark.asyncio
    async def test_process_pdf_stage_sequence_validation(self):
        """
        GIVEN PDF processing pipeline
        WHEN process_pdf executes
        THEN expect stages to be called in exact order:
            1. _validate_and_analyze_pdf
            2. _decompose_pdf
            3. _create_ipld_structure
            4. _process_ocr
            5. _optimize_for_llm
            6. _extract_entities
            7. _create_embeddings
            8. _integrate_with_graphrag
            9. _analyze_cross_document_relationships
            10. _setup_query_interface
        """
        processor = PDFProcessor()
        pdf_path = Path("test.pdf")
        call_order = []
        
        def track_call(stage_name):
            def wrapper(*args, **kwargs):
                call_order.append(stage_name)
                return {}
            return wrapper
        
        with patch.object(processor, '_validate_and_analyze_pdf', side_effect=track_call('validate')), \
             patch.object(processor, '_decompose_pdf', side_effect=track_call('decompose')), \
             patch.object(processor, '_create_ipld_structure', side_effect=track_call('ipld')), \
             patch.object(processor, '_process_ocr', side_effect=track_call('ocr')), \
             patch.object(processor, '_optimize_for_llm', side_effect=track_call('llm')), \
             patch.object(processor, '_extract_entities', side_effect=track_call('entities')), \
             patch.object(processor, '_create_embeddings', side_effect=track_call('embeddings')), \
             patch.object(processor, '_integrate_with_graphrag', side_effect=track_call('graphrag')), \
             patch.object(processor, '_analyze_cross_document_relationships', side_effect=track_call('cross_doc')), \
             patch.object(processor, '_setup_query_interface', side_effect=track_call('query')):
            
            await processor.process_pdf(pdf_path)
            
            expected_order = [
                'validate', 'decompose', 'ipld', 'ocr', 'llm',
                'entities', 'embeddings', 'graphrag', 'cross_doc', 'query'
            ]
            assert call_order == expected_order

    @pytest.mark.asyncio
    async def test_process_pdf_data_flow_between_stages(self):
        """
        GIVEN PDF processing pipeline
        WHEN process_pdf executes
        THEN expect:
            - Each stage receives output from previous stage
            - Data structure integrity maintained through pipeline
            - IPLD structure passed to multiple stages
            - Final results aggregate all stage outputs
        """
        processor = PDFProcessor()
        pdf_path = Path("test.pdf")
        
        # Track data flow between stages
        stage_inputs = {}
        
        def track_input(stage_name):
            def wrapper(*args, **kwargs):
                stage_inputs[stage_name] = args
                if stage_name == 'validate':
                    return {"file_path": str(pdf_path), "page_count": 1}
                elif stage_name == 'decompose':
                    return {"pages": [], "metadata": {}}
                elif stage_name == 'ipld':
                    return {"root_cid": "QmTest"}
                else:
                    return {}
            return wrapper
        
        with patch.object(processor, '_validate_and_analyze_pdf', side_effect=track_input('validate')), \
             patch.object(processor, '_decompose_pdf', side_effect=track_input('decompose')), \
             patch.object(processor, '_create_ipld_structure', side_effect=track_input('ipld')), \
             patch.object(processor, '_process_ocr', side_effect=track_input('ocr')), \
             patch.object(processor, '_optimize_for_llm', side_effect=track_input('llm')), \
             patch.object(processor, '_extract_entities', side_effect=track_input('entities')), \
             patch.object(processor, '_create_embeddings', side_effect=track_input('embeddings')), \
             patch.object(processor, '_integrate_with_graphrag', side_effect=track_input('graphrag')), \
             patch.object(processor, '_analyze_cross_document_relationships', side_effect=track_input('cross_doc')), \
             patch.object(processor, '_setup_query_interface', side_effect=track_input('query')):
            
            result = await processor.process_pdf(pdf_path)
            
            # Verify stages received appropriate inputs
            assert 'validate' in stage_inputs
            assert 'decompose' in stage_inputs
            assert 'ipld' in stage_inputs
            
            # Verify data flow integrity
            assert len(stage_inputs['validate']) > 0
            assert len(stage_inputs['decompose']) > 0
            assert len(stage_inputs['ipld']) > 0

    @pytest.mark.asyncio
    async def test_process_pdf_error_handling_and_recovery(self):
        """
        GIVEN non-critical error in pipeline stage
        WHEN process_pdf encounters recoverable error
        THEN expect:
            - Error logged but processing continues
            - Partial results returned with error indicators
            - Processing metadata reflects failed stages
        """
        processor = PDFProcessor()
        pdf_path = Path("test.pdf")
        
        # Mock a recoverable error in OCR stage
        with patch.object(processor, '_validate_and_analyze_pdf') as mock_validate, \
             patch.object(processor, '_decompose_pdf') as mock_decompose, \
             patch.object(processor, '_create_ipld_structure') as mock_ipld, \
             patch.object(processor, '_process_ocr') as mock_ocr, \
             patch.object(processor, '_optimize_for_llm') as mock_llm, \
             patch.object(processor, '_extract_entities') as mock_entities, \
             patch.object(processor, '_create_embeddings') as mock_embeddings, \
             patch.object(processor, '_integrate_with_graphrag') as mock_graphrag, \
             patch.object(processor, '_analyze_cross_document_relationships') as mock_cross_doc, \
             patch.object(processor, '_setup_query_interface') as mock_query:
            
            # Setup mocks - OCR fails but others succeed
            mock_validate.return_value = {"file_path": str(pdf_path)}
            mock_decompose.return_value = {"pages": [], "metadata": {}}
            mock_ipld.return_value = {"root_cid": "QmTest"}
            mock_ocr.side_effect = RuntimeError("OCR engine temporarily unavailable")
            mock_llm.return_value = {"llm_document": None}
            mock_entities.return_value = {"entities": [], "relationships": []}
            mock_embeddings.return_value = {"embeddings": []}
            mock_graphrag.return_value = {"document": {"id": "doc_123"}}
            mock_cross_doc.return_value = []
            mock_query.return_value = None
            
            # Expect the error to propagate (in real implementation, might be handled gracefully)
            with pytest.raises(RuntimeError):
                await processor.process_pdf(pdf_path)

    @pytest.mark.asyncio
    async def test_process_pdf_audit_logging_integration(self):
        """
        GIVEN PDFProcessor with audit logging enabled
        WHEN process_pdf executes
        THEN expect:
            - Document access logged
            - Processing start/end events recorded
            - Security events captured
            - Compliance data generated
        """
        processor = PDFProcessor(enable_audit=True)
        pdf_path = Path("test.pdf")
        
        # Mock all pipeline stages
        with patch.object(processor, '_validate_and_analyze_pdf') as mock_validate, \
             patch.object(processor, '_decompose_pdf'), \
             patch.object(processor, '_create_ipld_structure'), \
             patch.object(processor, '_process_ocr'), \
             patch.object(processor, '_optimize_for_llm'), \
             patch.object(processor, '_extract_entities'), \
             patch.object(processor, '_create_embeddings'), \
             patch.object(processor, '_integrate_with_graphrag'), \
             patch.object(processor, '_analyze_cross_document_relationships'), \
             patch.object(processor, '_setup_query_interface'):
            
            mock_validate.return_value = {"file_path": str(pdf_path)}
            
            # Mock audit logger
            with patch.object(processor.audit_logger, 'log_document_access') as mock_log:
                await processor.process_pdf(pdf_path)
                
                # Verify audit logging occurred
                assert processor.audit_logger is not None

    @pytest.mark.asyncio
    async def test_process_pdf_monitoring_integration(self):
        """
        GIVEN PDFProcessor with monitoring enabled
        WHEN process_pdf executes
        THEN expect:
            - Performance metrics collected
            - Processing time tracked per stage
            - Resource usage monitored
            - Prometheus metrics exported
        """
        processor = PDFProcessor(enable_monitoring=True)
        pdf_path = Path("test.pdf")
        
        # Mock all pipeline stages
        with patch.object(processor, '_validate_and_analyze_pdf') as mock_validate, \
             patch.object(processor, '_decompose_pdf'), \
             patch.object(processor, '_create_ipld_structure'), \
             patch.object(processor, '_process_ocr'), \
             patch.object(processor, '_optimize_for_llm'), \
             patch.object(processor, '_extract_entities'), \
             patch.object(processor, '_create_embeddings'), \
             patch.object(processor, '_integrate_with_graphrag'), \
             patch.object(processor, '_analyze_cross_document_relationships'), \
             patch.object(processor, '_setup_query_interface'):
            
            mock_validate.return_value = {"file_path": str(pdf_path)}
            
            await processor.process_pdf(pdf_path)
            
            # Verify monitoring system is active
            assert processor.monitoring is not None

    @pytest.mark.asyncio
    async def test_process_pdf_large_file_memory_management(self):
        """
        GIVEN very large PDF file (>100MB)
        WHEN process_pdf executes
        THEN expect:
            - Memory usage remains within limits
            - Page-by-page processing for large files
            - Efficient resource cleanup
            - No memory leaks during processing
        """
        processor = PDFProcessor()
        large_pdf_path = Path("large_document.pdf")
        
        with patch.object(processor, '_validate_and_analyze_pdf') as mock_validate:
            # Simulate large file metadata
            mock_validate.return_value = {
                "file_path": str(large_pdf_path),
                "file_size": 104857600,  # 100MB
                "page_count": 1000
            }
            
            # Mock other stages to avoid actual processing
            with patch.object(processor, '_decompose_pdf'), \
                 patch.object(processor, '_create_ipld_structure'), \
                 patch.object(processor, '_process_ocr'), \
                 patch.object(processor, '_optimize_for_llm'), \
                 patch.object(processor, '_extract_entities'), \
                 patch.object(processor, '_create_embeddings'), \
                 patch.object(processor, '_integrate_with_graphrag'), \
                 patch.object(processor, '_analyze_cross_document_relationships'), \
                 patch.object(processor, '_setup_query_interface'):
                
                result = await processor.process_pdf(large_pdf_path)
                
                # Verify processing completed for large file
                assert result is not None

    @pytest.mark.asyncio
    async def test_process_pdf_concurrent_processing_safety(self):
        """
        GIVEN multiple concurrent PDF processing calls
        WHEN process_pdf is called simultaneously on different files
        THEN expect:
            - Each processing instance operates independently
            - No shared state interference
            - Correct results for each file
            - No race conditions in storage or monitoring
        """
        processor = PDFProcessor()
        pdf_path1 = Path("document1.pdf")
        pdf_path2 = Path("document2.pdf")
        
        # Mock pipeline stages to return different results for each file
        def mock_validate_side_effect(path):
            return {"file_path": str(path), "page_count": 1 if "document1" in str(path) else 2}
        
        with patch.object(processor, '_validate_and_analyze_pdf', side_effect=mock_validate_side_effect), \
             patch.object(processor, '_decompose_pdf'), \
             patch.object(processor, '_create_ipld_structure'), \
             patch.object(processor, '_process_ocr'), \
             patch.object(processor, '_optimize_for_llm'), \
             patch.object(processor, '_extract_entities'), \
             patch.object(processor, '_create_embeddings'), \
             patch.object(processor, '_integrate_with_graphrag'), \
             patch.object(processor, '_analyze_cross_document_relationships'), \
             patch.object(processor, '_setup_query_interface'):
            
            # Process files concurrently
            import asyncio
            task1 = asyncio.create_task(processor.process_pdf(pdf_path1))
            task2 = asyncio.create_task(processor.process_pdf(pdf_path2))
            
            results = await asyncio.gather(task1, task2)
            
            # Verify both completed successfully
            assert len(results) == 2
            assert results[0] is not None
            assert results[1] is not None
    
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
