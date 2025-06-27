"""
Unit tests for MCP server PDF tools.
"""

import pytest
import json
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from pathlib import Path

# Import MCP tools
from ipfs_datasets_py.mcp_server.tools.pdf_tools import (
    pdf_ingest_to_graphrag,
    pdf_query_corpus, 
    pdf_extract_entities,
    pdf_batch_process,
    pdf_analyze_relationships,
    pdf_optimize_for_llm,
    pdf_cross_document_analysis
)


class TestPDFIngestToGraphRAG:
    """Test the PDF ingest to GraphRAG MCP tool."""
    
    @pytest.mark.asyncio
    async def test_pdf_ingest_basic(self, temp_dir, sample_ipld_structure):
        """Test basic PDF ingestion functionality."""
        # Create a mock PDF file
        pdf_path = temp_dir / "test.pdf"
        pdf_path.write_text("mock pdf content")
        
        request_data = {
            "pdf_path": str(pdf_path),
            "options": {
                "enable_ocr": True,
                "chunk_size": 1024,
                "overlap": 200
            }
        }
        
        # Mock the PDF processor
        with patch('ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_ingest_to_graphrag.PDFProcessor') as mock_processor_class:
            mock_processor = Mock()
            mock_processor.process_pdf = AsyncMock(return_value={
                "status": "success",
                "document_id": "test_doc_001",
                "chunks_created": 8,
                "entities_extracted": 12,
                "processing_time": "45.2s"
            })
            mock_processor_class.return_value = mock_processor
            
            result = await pdf_ingest_to_graphrag(json.dumps(request_data))
            
            assert "content" in result
            response_content = json.loads(result["content"][0]["text"])
            assert response_content["status"] == "success"
            assert response_content["document_id"] == "test_doc_001"
            assert response_content["chunks_created"] == 8
    
    @pytest.mark.asyncio
    async def test_pdf_ingest_with_metadata(self, temp_dir):
        """Test PDF ingestion with custom metadata."""
        pdf_path = temp_dir / "research.pdf"
        pdf_path.write_text("research content")
        
        request_data = {
            "pdf_path": str(pdf_path),
            "metadata": {
                "author": "Dr. Smith",
                "category": "research",
                "tags": ["ai", "machine-learning"]
            },
            "options": {
                "enable_llm_optimization": True
            }
        }
        
        with patch('ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_ingest_to_graphrag.PDFProcessor') as mock_processor_class:
            mock_processor = Mock()
            mock_processor.process_pdf = AsyncMock(return_value={
                "status": "success",
                "document_id": "research_001"
            })
            mock_processor_class.return_value = mock_processor
            
            result = await pdf_ingest_to_graphrag(json.dumps(request_data))
            
            # Verify metadata was passed
            call_args = mock_processor.process_pdf.call_args
            assert call_args[1]["metadata"]["author"] == "Dr. Smith"
            assert "ai" in call_args[1]["metadata"]["tags"]
    
    @pytest.mark.asyncio
    async def test_pdf_ingest_error_handling(self):
        """Test error handling in PDF ingestion."""
        request_data = {
            "pdf_path": "/nonexistent/file.pdf"
        }
        
        result = await pdf_ingest_to_graphrag(json.dumps(request_data))
        
        response_content = json.loads(result["content"][0]["text"])
        assert response_content["status"] == "error"
        assert "error" in response_content


class TestPDFQueryCorpus:
    """Test the PDF corpus querying MCP tool."""
    
    @pytest.mark.asyncio
    async def test_query_corpus_basic(self):
        """Test basic corpus querying."""
        request_data = {
            "query": "What is IPFS?",
            "query_type": "semantic_search",
            "max_results": 5
        }
        
        mock_results = [
            {
                "chunk_id": "chunk_001",
                "text": "IPFS is a peer-to-peer hypermedia protocol",
                "score": 0.95,
                "document_id": "doc_001"
            },
            {
                "chunk_id": "chunk_002", 
                "text": "IPFS uses content addressing",
                "score": 0.87,
                "document_id": "doc_001"
            }
        ]
        
        with patch('ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_query_corpus.QueryEngine') as mock_engine_class:
            mock_engine = Mock()
            mock_engine.query = AsyncMock(return_value={
                "results": mock_results,
                "total_found": 2,
                "query_time": "0.3s"
            })
            mock_engine_class.return_value = mock_engine
            
            result = await pdf_query_corpus(json.dumps(request_data))
            
            response_content = json.loads(result["content"][0]["text"])
            assert response_content["status"] == "success"
            assert len(response_content["results"]) == 2
            assert response_content["results"][0]["score"] == 0.95
    
    @pytest.mark.asyncio
    async def test_query_corpus_different_types(self):
        """Test different query types."""
        query_types = [
            "entity_search",
            "relationship_search", 
            "graph_traversal",
            "semantic_search"
        ]
        
        for query_type in query_types:
            request_data = {
                "query": f"Test query for {query_type}",
                "query_type": query_type
            }
            
            with patch('ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_query_corpus.QueryEngine') as mock_engine_class:
                mock_engine = Mock()
                mock_engine.query = AsyncMock(return_value={
                    "results": [],
                    "query_type": query_type,
                    "status": "success"
                })
                mock_engine_class.return_value = mock_engine
                
                result = await pdf_query_corpus(json.dumps(request_data))
                
                response_content = json.loads(result["content"][0]["text"])
                assert response_content["status"] == "success"
    
    @pytest.mark.asyncio
    async def test_query_corpus_with_filters(self):
        """Test corpus querying with filters."""
        request_data = {
            "query": "machine learning",
            "query_type": "semantic_search",
            "filters": {
                "document_category": "research",
                "min_similarity": 0.7,
                "date_range": {"start": "2024-01-01", "end": "2024-12-31"}
            }
        }
        
        with patch('ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_query_corpus.QueryEngine') as mock_engine_class:
            mock_engine = Mock()
            mock_engine.query = AsyncMock(return_value={
                "results": [],
                "filters_applied": request_data["filters"]
            })
            mock_engine_class.return_value = mock_engine
            
            result = await pdf_query_corpus(json.dumps(request_data))
            
            # Verify filters were passed to the query engine
            call_args = mock_engine.query.call_args
            assert "filters" in call_args[1]


class TestPDFExtractEntities:
    """Test the PDF entity extraction MCP tool."""
    
    @pytest.mark.asyncio
    async def test_extract_entities_basic(self):
        """Test basic entity extraction."""
        request_data = {
            "document_id": "doc_001",
            "entity_types": ["person", "organization", "technology"]
        }
        
        mock_entities = [
            {
                "entity_id": "ent_001",
                "name": "IPFS",
                "type": "technology",
                "confidence": 0.95,
                "mentions": [{"chunk_id": "chunk_001", "start": 0, "end": 4}]
            },
            {
                "entity_id": "ent_002",
                "name": "Protocol Labs",
                "type": "organization", 
                "confidence": 0.88,
                "mentions": [{"chunk_id": "chunk_003", "start": 15, "end": 28}]
            }
        ]
        
        with patch('ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_extract_entities.GraphRAGIntegrator') as mock_integrator_class:
            mock_integrator = Mock()
            mock_integrator.extract_entities = AsyncMock(return_value={
                "entities": mock_entities,
                "extraction_time": "2.1s"
            })
            mock_integrator_class.return_value = mock_integrator
            
            result = await pdf_extract_entities(json.dumps(request_data))
            
            response_content = json.loads(result["content"][0]["text"])
            assert response_content["status"] == "success"
            assert len(response_content["entities"]) == 2
            assert response_content["entities"][0]["name"] == "IPFS"
    
    @pytest.mark.asyncio
    async def test_extract_entities_with_relationships(self):
        """Test entity extraction including relationships."""
        request_data = {
            "document_id": "doc_001",
            "include_relationships": True,
            "min_confidence": 0.8
        }
        
        with patch('ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_extract_entities.GraphRAGIntegrator') as mock_integrator_class:
            mock_integrator = Mock()
            mock_integrator.extract_entities = AsyncMock(return_value={
                "entities": [],
                "relationships": [
                    {
                        "source": "IPFS",
                        "target": "Protocol Labs",
                        "relation": "developed_by",
                        "confidence": 0.9
                    }
                ]
            })
            mock_integrator_class.return_value = mock_integrator
            
            result = await pdf_extract_entities(json.dumps(request_data))
            
            response_content = json.loads(result["content"][0]["text"])
            assert "relationships" in response_content
            assert len(response_content["relationships"]) == 1


class TestPDFBatchProcess:
    """Test the PDF batch processing MCP tool."""
    
    @pytest.mark.asyncio
    async def test_batch_process_basic(self, temp_dir):
        """Test basic batch processing."""
        # Create multiple mock PDF files
        pdf_files = []
        for i in range(3):
            pdf_path = temp_dir / f"doc_{i}.pdf"
            pdf_path.write_text(f"content of document {i}")
            pdf_files.append(str(pdf_path))
        
        request_data = {
            "pdf_paths": pdf_files,
            "batch_options": {
                "max_workers": 2,
                "enable_progress_tracking": True
            }
        }
        
        with patch('ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_batch_process.BatchProcessor') as mock_processor_class:
            mock_processor = Mock()
            mock_processor.process_batch = AsyncMock(return_value={
                "batch_id": "batch_001",
                "status": "completed",
                "processed_count": 3,
                "failed_count": 0,
                "total_time": "2m 15s"
            })
            mock_processor_class.return_value = mock_processor
            
            result = await pdf_batch_process(json.dumps(request_data))
            
            response_content = json.loads(result["content"][0]["text"])
            assert response_content["status"] == "completed"
            assert response_content["processed_count"] == 3
            assert response_content["batch_id"] == "batch_001"
    
    @pytest.mark.asyncio
    async def test_batch_process_progress_tracking(self, temp_dir):
        """Test batch processing with progress tracking."""
        pdf_path = temp_dir / "test.pdf"
        pdf_path.write_text("test content")
        
        request_data = {
            "pdf_paths": [str(pdf_path)],
            "batch_options": {
                "enable_progress_tracking": True,
                "progress_callback_url": "http://localhost:8080/progress"
            }
        }
        
        with patch('ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_batch_process.BatchProcessor') as mock_processor_class:
            mock_processor = Mock()
            mock_processor.process_batch = AsyncMock(return_value={
                "batch_id": "batch_002",
                "status": "in_progress",
                "progress_url": "http://localhost:8080/batch/batch_002/status"
            })
            mock_processor_class.return_value = mock_processor
            
            result = await pdf_batch_process(json.dumps(request_data))
            
            response_content = json.loads(result["content"][0]["text"])
            assert "progress_url" in response_content
            assert response_content["batch_id"] == "batch_002"


class TestPDFAnalyzeRelationships:
    """Test the PDF relationship analysis MCP tool."""
    
    @pytest.mark.asyncio
    async def test_analyze_relationships_basic(self):
        """Test basic relationship analysis."""
        request_data = {
            "document_ids": ["doc_001", "doc_002"],
            "analysis_type": "cross_document",
            "relationship_types": ["semantic", "entity_based", "citation"]
        }
        
        mock_relationships = [
            {
                "source_doc": "doc_001",
                "target_doc": "doc_002",
                "relationship_type": "semantic_similarity",
                "strength": 0.87,
                "evidence": ["Both documents discuss IPFS protocol"]
            },
            {
                "source_entity": "IPFS",
                "target_entity": "BitTorrent",
                "relationship_type": "similar_technology",
                "strength": 0.72,
                "documents": ["doc_001", "doc_002"]
            }
        ]
        
        with patch('ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_analyze_relationships.GraphRAGIntegrator') as mock_integrator_class:
            mock_integrator = Mock()
            mock_integrator.analyze_relationships = AsyncMock(return_value={
                "relationships": mock_relationships,
                "analysis_time": "5.3s"
            })
            mock_integrator_class.return_value = mock_integrator
            
            result = await pdf_analyze_relationships(json.dumps(request_data))
            
            response_content = json.loads(result["content"][0]["text"])
            assert response_content["status"] == "success"
            assert len(response_content["relationships"]) == 2
            assert response_content["relationships"][0]["strength"] == 0.87
    
    @pytest.mark.asyncio
    async def test_analyze_relationships_with_filters(self):
        """Test relationship analysis with filters."""
        request_data = {
            "document_ids": ["doc_001"],
            "analysis_type": "intra_document",
            "filters": {
                "min_strength": 0.5,
                "max_distance": 3,
                "entity_types": ["person", "organization"]
            }
        }
        
        with patch('ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_analyze_relationships.GraphRAGIntegrator') as mock_integrator_class:
            mock_integrator = Mock()
            mock_integrator.analyze_relationships = AsyncMock(return_value={
                "relationships": [],
                "filters_applied": request_data["filters"]
            })
            mock_integrator_class.return_value = mock_integrator
            
            result = await pdf_analyze_relationships(json.dumps(request_data))
            
            # Verify filters were applied
            call_args = mock_integrator.analyze_relationships.call_args
            assert "filters" in call_args[1]


class TestMCPToolIntegration:
    """Test integration aspects of MCP tools."""
    
    def test_all_tools_importable(self):
        """Test that all MCP tools can be imported."""
        tools = [
            pdf_ingest_to_graphrag,
            pdf_query_corpus,
            pdf_extract_entities,
            pdf_batch_process,
            pdf_analyze_relationships,
            pdf_optimize_for_llm,
            pdf_cross_document_analysis
        ]
        
        for tool in tools:
            assert callable(tool)
    
    @pytest.mark.asyncio
    async def test_tool_error_handling_consistency(self):
        """Test that all tools handle errors consistently."""
        tools_data = [
            (pdf_ingest_to_graphrag, '{"invalid": "data"}'),
            (pdf_query_corpus, '{"malformed": true}'),
            (pdf_extract_entities, '{"bad_request": null}')
        ]
        
        for tool_func, bad_data in tools_data:
            result = await tool_func(bad_data)
            
            # All tools should return properly formatted MCP responses
            assert "content" in result
            assert len(result["content"]) > 0
            assert "text" in result["content"][0]
            
            # Parse response and check for error status
            response_content = json.loads(result["content"][0]["text"])
            assert response_content["status"] == "error"
    
    @pytest.mark.asyncio
    async def test_tool_response_format_consistency(self, temp_dir):
        """Test that all tools return consistent response formats."""
        pdf_path = temp_dir / "test.pdf"
        pdf_path.write_text("test content")
        
        # Test with valid minimal data
        tools_data = [
            (pdf_ingest_to_graphrag, {"pdf_path": str(pdf_path)}),
            (pdf_query_corpus, {"query": "test", "query_type": "semantic_search"}),
            (pdf_extract_entities, {"document_id": "test_doc"}),
            (pdf_batch_process, {"pdf_paths": [str(pdf_path)]})
        ]
        
        for tool_func, request_data in tools_data:
            with patch.multiple(
                'ipfs_datasets_py.mcp_server.tools.pdf_tools',
                PDFProcessor=Mock,
                QueryEngine=Mock,
                GraphRAGIntegrator=Mock,
                BatchProcessor=Mock
            ):
                result = await tool_func(json.dumps(request_data))
                
                # Check MCP response format
                assert isinstance(result, dict)
                assert "content" in result
                assert isinstance(result["content"], list)
                assert len(result["content"]) > 0
                assert "type" in result["content"][0]
                assert "text" in result["content"][0]
                
                # Check JSON response format
                response_content = json.loads(result["content"][0]["text"])
                assert "status" in response_content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
