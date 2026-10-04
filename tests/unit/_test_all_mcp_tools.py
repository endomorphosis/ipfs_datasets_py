"""
Comprehensive unit tests for all MCP tools.
"""

import pytest
import json
import anyio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from pathlib import Path
import tempfile
import time

# Import all major MCP tool categories
from ipfs_datasets_py.mcp_server.tools.dataset_tools import (
    load_dataset,
    save_dataset, 
    process_dataset,
    convert_dataset_format
)

from ipfs_datasets_py.mcp_server.tools.ipfs_tools import (
    pin_to_ipfs,
    get_from_ipfs
)

from ipfs_datasets_py.mcp_server.tools.audit_tools import (
    record_audit_event,
    generate_audit_report
)

from ipfs_datasets_py.mcp_server.tools.vector_tools import (
    create_vector_index,
    search_vector_index
)

from ipfs_datasets_py.mcp_server.tools.security_tools import (
    check_access_permission
)

# Also test PDF tools
from ipfs_datasets_py.mcp_server.tools.pdf_tools import (
    pdf_ingest_to_graphrag,
    pdf_query_corpus,
    pdf_extract_entities,
    pdf_batch_process,
    pdf_analyze_relationships,
    pdf_optimize_for_llm,
    pdf_cross_document_analysis
)


class TestDatasetTools:
    """Test dataset management MCP tools."""
    
    @pytest.mark.asyncio
    async def test_load_dataset_tool(self):
        """Test the load_dataset MCP tool."""
        request_data = {
            "source": "test_dataset",
            "format": "json",
            "options": {"subset": "train"}
        }
        
        # Mock the dataset loading
        with patch('ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset.ipfs_datasets') as mock_datasets:
            mock_datasets.load_dataset.return_value = {
                "dataset_id": "test_dataset_001",
                "records": 1000,
                "format": "json"
            }
            
            result = await load_dataset(json.dumps(request_data))
            
            assert "content" in result
            response_data = json.loads(result["content"][0]["text"])
            assert response_data["status"] == "success"
            assert response_data["dataset_id"] == "test_dataset_001"
    
    @pytest.mark.asyncio
    async def test_save_dataset_tool(self, temp_dir):
        """Test the save_dataset MCP tool."""
        output_path = temp_dir / "output.json"
        
        request_data = {
            "dataset_data": {"data": "test content"},
            "destination": str(output_path),
            "format": "json"
        }
        
        with patch('ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset.ipfs_datasets') as mock_datasets:
            mock_datasets.save_dataset.return_value = {
                "saved_path": str(output_path),
                "size": "1.2KB",
                "format": "json"
            }
            
            result = await save_dataset(json.dumps(request_data))
            
            response_data = json.loads(result["content"][0]["text"])
            assert response_data["status"] == "success"
            assert response_data["saved_path"] == str(output_path)
    
    @pytest.mark.asyncio
    async def test_process_dataset_tool(self):
        """Test the process_dataset MCP tool."""
        request_data = {
            "dataset_source": "test_dataset_001",
            "operations": [
                {"type": "filter", "column": "score", "condition": ">", "value": 0.5},
                {"type": "select", "columns": ["id", "text", "score"]}
            ]
        }
        
        with patch('ipfs_datasets_py.mcp_server.tools.dataset_tools.process_dataset.ipfs_datasets') as mock_datasets:
            mock_datasets.process_dataset.return_value = {
                "dataset_id": "processed_dataset_001",
                "operations_applied": 2,
                "records_remaining": 750
            }
            
            result = await process_dataset(json.dumps(request_data))
            
            response_data = json.loads(result["content"][0]["text"])
            assert response_data["status"] == "success"
            assert response_data["operations_applied"] == 2
    
    @pytest.mark.asyncio
    async def test_convert_dataset_format_tool(self):
        """Test the convert_dataset_format MCP tool."""
        request_data = {
            "dataset_id": "test_dataset_001",
            "target_format": "parquet",
            "options": {"compression": "snappy"}
        }
        
        with patch('ipfs_datasets_py.mcp_server.tools.dataset_tools.convert_dataset_format.ipfs_datasets') as mock_datasets:
            mock_datasets.convert_dataset_format.return_value = {
                "converted_dataset_id": "converted_dataset_001",
                "target_format": "parquet",
                "compression_ratio": 0.75
            }
            
            result = await convert_dataset_format(json.dumps(request_data))
            
            response_data = json.loads(result["content"][0]["text"])
            assert response_data["status"] == "success"
            assert response_data["target_format"] == "parquet"


class TestIPFSTools:
    """Test IPFS interaction MCP tools."""
    
    @pytest.mark.asyncio
    async def test_pin_to_ipfs_tool(self, temp_dir):
        """Test the pin_to_ipfs MCP tool."""
        test_file = temp_dir / "test_data.json"
        test_file.write_text('{"test": "data"}')
        
        request_data = {
            "content_source": str(test_file),
            "recursive": True,
            "wrap_with_directory": False
        }
        
        with patch('ipfs_datasets_py.mcp_server.tools.ipfs_tools.pin_to_ipfs.ipfs_datasets') as mock_datasets:
            mock_datasets.pin_to_ipfs.return_value = {
                "cid": "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
                "size": 1024,
                "pinned": True
            }
            
            result = await pin_to_ipfs(json.dumps(request_data))
            
            response_data = json.loads(result["content"][0]["text"])
            assert response_data["status"] == "success"
            assert "cid" in response_data
            assert response_data["pinned"] is True
    
    @pytest.mark.asyncio
    async def test_get_from_ipfs_tool(self, temp_dir):
        """Test the get_from_ipfs MCP tool."""
        output_path = temp_dir / "retrieved_data.json"
        
        request_data = {
            "cid": "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
            "output_path": str(output_path),
            "timeout_seconds": 30
        }
        
        with patch('ipfs_datasets_py.mcp_server.tools.ipfs_tools.get_from_ipfs.ipfs_datasets') as mock_datasets:
            mock_datasets.get_from_ipfs.return_value = {
                "retrieved_path": str(output_path),
                "size": 1024,
                "retrieval_time": "2.3s"
            }
            
            result = await get_from_ipfs(json.dumps(request_data))
            
            response_data = json.loads(result["content"][0]["text"])
            assert response_data["status"] == "success"
            assert response_data["retrieved_path"] == str(output_path)


class TestAuditTools:
    """Test audit and logging MCP tools."""
    
    @pytest.mark.asyncio
    async def test_record_audit_event_tool(self):
        """Test the record_audit_event MCP tool."""
        request_data = {
            "action": "dataset.access",
            "resource_id": "dataset_001",
            "user_id": "user_123",
            "details": {"operation": "read", "success": True},
            "severity": "info"
        }
        
        with patch('ipfs_datasets_py.mcp_server.tools.audit_tools.record_audit_event.AuditLogger') as mock_logger:
            mock_audit = Mock()
            mock_logger.get_instance.return_value = mock_audit
            
            result = await record_audit_event(json.dumps(request_data))
            
            response_data = json.loads(result["content"][0]["text"])
            assert response_data["status"] == "success"
            assert "event_id" in response_data
    
    @pytest.mark.asyncio
    async def test_generate_audit_report_tool(self, temp_dir):
        """Test the generate_audit_report MCP tool."""
        report_path = temp_dir / "audit_report.html"
        
        request_data = {
            "report_type": "security",
            "start_time": "2024-01-01T00:00:00Z",
            "end_time": "2024-12-31T23:59:59Z",
            "output_path": str(report_path),
            "output_format": "html"
        }
        
        with patch('ipfs_datasets_py.mcp_server.tools.audit_tools.generate_audit_report.ipfs_datasets') as mock_datasets:
            mock_datasets.generate_audit_report.return_value = {
                "report_path": str(report_path),
                "events_processed": 1500,
                "report_type": "security",
                "generation_time": "5.2s"
            }
            
            result = await generate_audit_report(json.dumps(request_data))
            
            response_data = json.loads(result["content"][0]["text"])
            assert response_data["status"] == "success"
            assert response_data["events_processed"] == 1500


class TestVectorTools:
    """Test vector search MCP tools."""
    
    @pytest.mark.asyncio
    async def test_create_vector_index_tool(self):
        """Test the create_vector_index MCP tool."""
        request_data = {
            "vectors": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6], [0.7, 0.8, 0.9]],
            "dimension": 3,
            "metric": "cosine",
            "metadata": [
                {"id": 1, "text": "first vector"},
                {"id": 2, "text": "second vector"}, 
                {"id": 3, "text": "third vector"}
            ],
            "index_name": "test_index"
        }
        
        with patch('ipfs_datasets_py.mcp_server.tools.vector_tools.create_vector_index.ipfs_datasets') as mock_datasets:
            mock_datasets.create_vector_index.return_value = {
                "index_id": "vector_index_001",
                "vectors_indexed": 3,
                "dimension": 3,
                "metric": "cosine"
            }
            
            result = await create_vector_index(json.dumps(request_data))
            
            response_data = json.loads(result["content"][0]["text"])
            assert response_data["status"] == "success"
            assert response_data["vectors_indexed"] == 3
    
    @pytest.mark.asyncio
    async def test_search_vector_index_tool(self):
        """Test the search_vector_index MCP tool."""
        request_data = {
            "index_id": "vector_index_001",
            "query_vector": [0.1, 0.2, 0.3],
            "top_k": 5,
            "include_metadata": True,
            "include_distances": True
        }
        
        with patch('ipfs_datasets_py.mcp_server.tools.vector_tools.search_vector_index.ipfs_datasets') as mock_datasets:
            mock_datasets.search_vector_index.return_value = {
                "results": [
                    {"id": 1, "distance": 0.1, "metadata": {"text": "first match"}},
                    {"id": 2, "distance": 0.3, "metadata": {"text": "second match"}}
                ],
                "query_time": "0.05s"
            }
            
            result = await search_vector_index(json.dumps(request_data))
            
            response_data = json.loads(result["content"][0]["text"])
            assert response_data["status"] == "success"
            assert len(response_data["results"]) == 2


class TestSecurityTools:
    """Test security and access control MCP tools."""
    
    @pytest.mark.asyncio
    async def test_check_access_permission_tool(self):
        """Test the check_access_permission MCP tool."""
        request_data = {
            "resource_id": "dataset_001",
            "user_id": "user_123",
            "permission_type": "read",
            "resource_type": "dataset"
        }
        
        with patch('ipfs_datasets_py.mcp_server.tools.security_tools.check_access_permission.ipfs_datasets') as mock_datasets:
            mock_datasets.check_access_permission.return_value = {
                "access_granted": True,
                "permission_type": "read",
                "user_id": "user_123",
                "resource_id": "dataset_001",
                "conditions": []
            }
            
            result = await check_access_permission(json.dumps(request_data))
            
            response_data = json.loads(result["content"][0]["text"])
            assert response_data["status"] == "success"
            assert response_data["access_granted"] is True


class TestPDFToolsComprehensive:
    """Comprehensive tests for all PDF processing MCP tools."""
    
    @pytest.mark.asyncio
    async def test_pdf_ingest_to_graphrag_comprehensive(self, temp_dir):
        """Test PDF ingestion with comprehensive options."""
        pdf_path = temp_dir / "comprehensive_test.pdf"
        pdf_path.write_text("Comprehensive PDF test content")
        
        request_data = {
            "pdf_path": str(pdf_path),
            "metadata": {
                "title": "Comprehensive Test Document",
                "author": "Test Suite",
                "category": "integration_test"
            },
            "options": {
                "enable_ocr": True,
                "enable_llm_optimization": True,
                "enable_entity_extraction": True,
                "chunk_size": 1024,
                "overlap": 200,
                "ocr_engines": ["surya", "tesseract"],
                "llm_model": "all-MiniLM-L6-v2"
            }
        }
        
        with patch('ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_ingest_to_graphrag.PDFProcessor') as mock_processor:
            mock_proc = Mock()
            mock_proc.process_pdf = AsyncMock(return_value={
                "status": "success",
                "document_id": "comprehensive_doc_001",
                "chunks_created": 15,
                "entities_extracted": 25,
                "relationships_found": 12,
                "processing_time": "2m 15s",
                "ipld_cid": "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
                "ocr_confidence": 0.94,
                "llm_optimization_applied": True
            })
            mock_processor.return_value = mock_proc
            
            result = await pdf_ingest_to_graphrag(json.dumps(request_data))
            
            response_data = json.loads(result["content"][0]["text"])
            assert response_data["status"] == "success"
            assert response_data["chunks_created"] == 15
            assert response_data["entities_extracted"] == 25
            assert response_data["llm_optimization_applied"] is True
    
    @pytest.mark.asyncio
    async def test_pdf_query_corpus_all_types(self):
        """Test all PDF query types."""
        query_types = [
            ("semantic_search", "What is IPFS?"),
            ("entity_search", "Find all technology entities"),
            ("relationship_search", "How are IPFS and peer-to-peer related?"),
            ("graph_traversal", "Show path from storage to security")
        ]
        
        for query_type, query_text in query_types:
            request_data = {
                "query": query_text,
                "query_type": query_type,
                "max_results": 10,
                "filters": {
                    "document_categories": ["research", "technical"],
                    "min_confidence": 0.7
                }
            }
            
            with patch('ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_query_corpus.QueryEngine') as mock_engine:
                mock_eng = Mock()
                mock_eng.query = AsyncMock(return_value={
                    "results": [
                        {
                            "chunk_id": f"{query_type}_result_001",
                            "text": f"Result for {query_text}",
                            "score": 0.95,
                            "query_type": query_type
                        }
                    ],
                    "total_found": 1,
                    "query_time": "0.3s"
                })
                mock_engine.return_value = mock_eng
                
                result = await pdf_query_corpus(json.dumps(request_data))
                
                response_data = json.loads(result["content"][0]["text"])
                assert response_data["status"] == "success"
                assert len(response_data["results"]) == 1
                assert response_data["results"][0]["query_type"] == query_type
    
    @pytest.mark.asyncio
    async def test_pdf_extract_entities_advanced(self):
        """Test advanced entity extraction options."""
        request_data = {
            "document_id": "test_doc_001",
            "entity_types": ["person", "organization", "technology", "concept", "location"],
            "include_relationships": True,
            "min_confidence": 0.8,
            "extraction_options": {
                "use_ner_models": ["spacy", "transformers"],
                "custom_patterns": [
                    {"label": "PROTOCOL", "pattern": [{"LOWER": {"IN": ["http", "https", "ipfs", "ftp"]}}]}
                ],
                "relationship_types": ["is_part_of", "developed_by", "used_in", "related_to"]
            }
        }
        
        with patch('ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_extract_entities.GraphRAGIntegrator') as mock_integrator:
            mock_int = Mock()
            mock_int.extract_entities = AsyncMock(return_value={
                "entities": [
                    {"name": "IPFS", "type": "technology", "confidence": 0.95},
                    {"name": "Protocol Labs", "type": "organization", "confidence": 0.88},
                    {"name": "San Francisco", "type": "location", "confidence": 0.82}
                ],
                "relationships": [
                    {"source": "IPFS", "target": "Protocol Labs", "type": "developed_by", "confidence": 0.9},
                    {"source": "Protocol Labs", "target": "San Francisco", "type": "located_in", "confidence": 0.85}
                ],
                "extraction_time": "3.2s",
                "models_used": ["spacy", "transformers"]
            })
            mock_integrator.return_value = mock_int
            
            result = await pdf_extract_entities(json.dumps(request_data))
            
            response_data = json.loads(result["content"][0]["text"])
            assert response_data["status"] == "success"
            assert len(response_data["entities"]) == 3
            assert len(response_data["relationships"]) == 2
            assert "models_used" in response_data
    
    @pytest.mark.asyncio
    async def test_pdf_batch_process_comprehensive(self, temp_dir):
        """Test comprehensive batch processing with monitoring."""
        # Create multiple test PDFs
        pdf_files = []
        for i in range(5):
            pdf_path = temp_dir / f"batch_doc_{i}.pdf"
            pdf_path.write_text(f"Batch document {i} content")
            pdf_files.append(str(pdf_path))
        
        request_data = {
            "pdf_paths": pdf_files,
            "batch_options": {
                "max_workers": 3,
                "enable_progress_tracking": True,
                "checkpoint_interval": 2,
                "retry_failed": True,
                "max_retries": 2
            },
            "processing_options": {
                "enable_ocr": True,
                "enable_llm_optimization": True,
                "chunk_size": 512,
                "overlap": 100
            }
        }
        
        with patch('ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_batch_process.BatchProcessor') as mock_processor:
            mock_proc = Mock()
            mock_proc.process_batch = AsyncMock(return_value={
                "batch_id": "batch_comprehensive_001",
                "status": "completed",
                "processed_count": 5,
                "failed_count": 0,
                "skipped_count": 0,
                "total_time": "8m 42s",
                "average_time_per_doc": "1m 44s",
                "checkpoints_created": 3,
                "progress_url": "http://localhost:8080/batch/batch_comprehensive_001/status"
            })
            mock_processor.return_value = mock_proc
            
            result = await pdf_batch_process(json.dumps(request_data))
            
            response_data = json.loads(result["content"][0]["text"])
            assert response_data["status"] == "completed"
            assert response_data["processed_count"] == 5
            assert response_data["failed_count"] == 0
            assert "progress_url" in response_data
    
    @pytest.mark.asyncio
    async def test_pdf_cross_document_analysis(self):
        """Test cross-document analysis capabilities."""
        request_data = {
            "document_ids": ["doc_001", "doc_002", "doc_003"],
            "analysis_types": ["semantic_similarity", "entity_overlap", "citation_network", "concept_evolution"],
            "options": {
                "similarity_threshold": 0.7,
                "max_connections": 100,
                "include_temporal_analysis": True,
                "generate_visualization": True
            }
        }
        
        with patch('ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_cross_document_analysis.CrossDocumentAnalyzer') as mock_analyzer:
            mock_an = Mock()
            mock_an.analyze_documents = AsyncMock(return_value={
                "analysis_id": "cross_analysis_001",
                "documents_analyzed": 3,
                "connections_found": 47,
                "similarity_clusters": [
                    {"documents": ["doc_001", "doc_002"], "similarity": 0.85, "topic": "IPFS protocol"},
                    {"documents": ["doc_002", "doc_003"], "similarity": 0.72, "topic": "peer-to-peer networks"}
                ],
                "entity_overlaps": [
                    {"entity": "IPFS", "documents": ["doc_001", "doc_002", "doc_003"], "frequency": [15, 23, 8]},
                    {"entity": "Protocol Labs", "documents": ["doc_001", "doc_002"], "frequency": [5, 7]}
                ],
                "temporal_evolution": {
                    "concepts": ["distributed storage", "content addressing", "merkle DAG"],
                    "evolution_path": "basic concepts → technical implementation → real-world applications"
                },
                "visualization_url": "http://localhost:8080/analysis/cross_analysis_001/viz.html"
            })
            mock_analyzer.return_value = mock_an
            
            result = await pdf_cross_document_analysis(json.dumps(request_data))
            
            response_data = json.loads(result["content"][0]["text"])
            assert response_data["status"] == "success"
            assert response_data["documents_analyzed"] == 3
            assert response_data["connections_found"] == 47
            assert len(response_data["similarity_clusters"]) == 2
            assert len(response_data["entity_overlaps"]) == 2
            assert "visualization_url" in response_data


class TestToolErrorHandling:
    """Test error handling across all MCP tools."""
    
    @pytest.mark.asyncio
    async def test_invalid_json_handling(self):
        """Test that all tools handle invalid JSON gracefully."""
        tools_to_test = [
            load_dataset,
            save_dataset,
            pdf_ingest_to_graphrag,
            pdf_query_corpus,
            pin_to_ipfs,
            record_audit_event
        ]
        
        invalid_inputs = [
            "not json",
            '{"incomplete": ',
            '{"null_value": null}',
            '{}',
            ''
        ]
        
        for tool in tools_to_test:
            for invalid_input in invalid_inputs:
                try:
                    result = await tool(invalid_input)
                    
                    # Should always return valid MCP response
                    assert "content" in result
                    assert len(result["content"]) > 0
                    
                    response_data = json.loads(result["content"][0]["text"])
                    assert response_data["status"] == "error"
                    assert "error" in response_data
                    
                except Exception as e:
                    pytest.fail(f"Tool {tool.__name__} failed to handle invalid input '{invalid_input}': {e}")
    
    @pytest.mark.asyncio
    async def test_missing_required_fields(self):
        """Test handling of missing required fields."""
        test_cases = [
            (load_dataset, {}),
            (save_dataset, {"dataset_data": "test"}),  # Missing destination
            (pdf_ingest_to_graphrag, {"options": {}}),  # Missing pdf_path
            (pdf_query_corpus, {"query_type": "semantic_search"}),  # Missing query
            (pin_to_ipfs, {"recursive": True}),  # Missing content_source
        ]
        
        for tool, incomplete_data in test_cases:
            result = await tool(json.dumps(incomplete_data))
            
            response_data = json.loads(result["content"][0]["text"])
            assert response_data["status"] == "error"
            assert "missing" in response_data["error"].lower() or "required" in response_data["error"].lower()
    
    @pytest.mark.asyncio
    async def test_timeout_handling(self):
        """Test timeout handling for long-running operations."""
        # Test with PDF batch processing
        request_data = {
            "pdf_paths": ["/mock/large_file1.pdf", "/mock/large_file2.pdf"],
            "batch_options": {"timeout": 1}  # Very short timeout
        }
        
        with patch('ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_batch_process.BatchProcessor') as mock_processor:
            mock_proc = Mock()
            
            # Simulate slow operation
            async def slow_process(*args, **kwargs):
                await anyio.sleep(2)  # Longer than timeout
                return {"status": "success"}
            
            mock_proc.process_batch = slow_process
            mock_processor.return_value = mock_proc
            
            # Test timeout handling
            try:
                result = await # TODO: Convert to anyio.fail_after() context manager
    asyncio.wait_for(
                    pdf_batch_process(json.dumps(request_data)),
                    timeout=1.5
                )
                # If no timeout, should still be valid response
                response_data = json.loads(result["content"][0]["text"])
                assert "status" in response_data
            except TimeoutError:
                # Timeout is acceptable for this test
                pass


class TestToolPerformance:
    """Test performance characteristics of MCP tools."""
    
    @pytest.mark.asyncio
    async def test_response_time_benchmarks(self):
        """Test that tools respond within reasonable time limits."""
        quick_tools = [
            (record_audit_event, {"action": "test.action"}),
            (check_access_permission, {"resource_id": "test", "user_id": "test"}),
            (load_dataset, {"source": "test_dataset"})
        ]
        
        for tool, minimal_data in quick_tools:
            start_time = time.time()
            
            # Mock any external dependencies
            with patch.multiple(
                'ipfs_datasets_py.mcp_server.tools',
                AuditLogger=Mock,
                ipfs_datasets=Mock,
                SecurityManager=Mock
            ):
                result = await tool(json.dumps(minimal_data))
            
            end_time = time.time()
            execution_time = end_time - start_time
            
            # Should complete quickly (under 1 second for mocked operations)
            assert execution_time < 1.0, f"Tool {tool.__name__} took {execution_time:.2f}s"
            
            # Should return valid response
            assert "content" in result
    
    @pytest.mark.asyncio
    async def test_concurrent_tool_execution(self):
        """Test concurrent execution of multiple tools."""
        tools_and_data = [
            (load_dataset, {"source": "dataset1"}),
            (record_audit_event, {"action": "test1"}),
            (check_access_permission, {"resource_id": "res1", "user_id": "user1"}),
            (load_dataset, {"source": "dataset2"}),
            (record_audit_event, {"action": "test2"})
        ]
        
        # Mock all external dependencies
        with patch.multiple(
            'ipfs_datasets_py.mcp_server.tools',
            AuditLogger=Mock,
            ipfs_datasets=Mock,
            SecurityManager=Mock
        ):
            # Execute tools concurrently
            tasks = [tool(json.dumps(data)) for tool, data in tools_and_data]
            results = await # TODO: Convert to anyio.create_task_group() - see anyio_migration_helpers.py
    asyncio.gather(*tasks, return_exceptions=True)
            
            # All should complete successfully
            assert len(results) == 5
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    pytest.fail(f"Tool {i} failed with exception: {result}")
                assert "content" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
