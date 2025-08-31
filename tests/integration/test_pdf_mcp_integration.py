# """
# Integration tests for PDF processing pipeline and MCP server.
# """

# import pytest
# import asyncio
# import json
# import tempfile
# from pathlib import Path
# from unittest.mock import patch, Mock, AsyncMock
# import time

# from ipfs_datasets_py.pdf_processing import PDFProcessor, LLMOptimizer, MultiEngineOCR
# from ipfs_datasets_py.mcp_server.tools.pdf_tools import pdf_ingest_to_graphrag, pdf_query_corpus


# class TestPDFProcessingIntegration:
#     """Integration tests for the complete PDF processing pipeline."""
    
#     @pytest.mark.asyncio
#     async def test_end_to_end_pdf_processing(self, temp_dir, sample_pdf_content):
#         """Test the complete end-to-end PDF processing pipeline."""
#         # Create a mock PDF file
#         pdf_path = temp_dir / "integration_test.pdf"
#         pdf_path.write_text("Integration test PDF content")
        
#         # Initialize components
#         processor = PDFProcessor(enable_monitoring=False, enable_audit=False)
        
#         # Mock the complex operations to avoid external dependencies
#         with patch.object(processor, '_extract_text_and_images') as mock_extract, \
#              patch.object(processor, '_process_with_ocr') as mock_ocr, \
#              patch.object(processor, '_optimize_with_llm') as mock_llm, \
#              patch.object(processor, '_create_knowledge_graph') as mock_kg, \
#              patch.object(processor, '_store_in_ipld') as mock_ipld:
            
#             # Set up mock responses
#             mock_extract.return_value = sample_pdf_content
#             mock_ocr.return_value = {"text": "OCR processed text", "confidence": 0.9}
#             mock_llm.return_value = {
#                 "optimized_chunks": [
#                     {"text": "Chunk 1", "metadata": {}},
#                     {"text": "Chunk 2", "metadata": {}}
#                 ],
#                 "summary": "Document summary"
#             }
#             mock_kg.return_value = {
#                 "entities": [{"name": "IPFS", "type": "technology"}],
#                 "relationships": [{"source": "IPFS", "target": "Protocol", "type": "uses"}]
#             }
#             mock_ipld.return_value = {
#                 "cid": "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
#                 "size": 1024
#             }
            
#             # Run the complete pipeline
#             result = await processor.process_pdf(str(pdf_path))
            
#             # Verify the pipeline executed all steps
#             assert result["status"] == "success"
#             assert "document_id" in result
#             assert "processing_time" in result
            
#             # Verify all pipeline steps were called
#             mock_extract.assert_called_once()
#             mock_llm.assert_called_once()
#             mock_kg.assert_called_once()
#             mock_ipld.assert_called_once()
    
#     @pytest.mark.asyncio
#     async def test_pdf_processing_with_real_components(self, temp_dir):
#         """Test PDF processing with real components (but mocked heavy operations)."""
#         pdf_path = temp_dir / "real_test.pdf"
#         pdf_path.write_text("Real component test")
        
#         # Use real components but mock the heavy operations
#         processor = PDFProcessor(enable_monitoring=False, enable_audit=False)
#         llm_optimizer = LLMOptimizer()
#         ocr_engine = MultiEngineOCR()
        
#         # Mock sentence transformers to avoid model downloads
#         with patch('sentence_transformers.SentenceTransformer') as mock_st:
#             mock_model = Mock()
#             mock_model.encode.return_value = [[0.1] * 768]  # Mock embedding
#             mock_st.return_value = mock_model
            
#             # Test individual components
#             chunks = await llm_optimizer.chunk_text("Test text for chunking")
#             assert len(chunks) > 0
#             assert all("text" in chunk for chunk in chunks)
            
#             # Test OCR engine initialization
#             assert ocr_engine.primary_engine == "surya"
#             assert len(ocr_engine.fallback_engines) > 0
    
#     @pytest.mark.asyncio
#     async def test_error_recovery_in_pipeline(self, temp_dir):
#         """Test error recovery mechanisms in the pipeline."""
#         pdf_path = temp_dir / "error_test.pdf"
#         pdf_path.write_text("Error recovery test")
        
#         processor = PDFProcessor(enable_monitoring=False, enable_audit=False)
        
#         # Simulate OCR failure but pipeline continues
#         with patch.object(processor, '_extract_text_and_images') as mock_extract, \
#              patch.object(processor, '_process_with_ocr') as mock_ocr, \
#              patch.object(processor, '_optimize_with_llm') as mock_llm:
            
#             mock_extract.return_value = {"text": "Basic text", "pages": []}
#             mock_ocr.side_effect = Exception("OCR failed")  # OCR fails
#             mock_llm.return_value = {"optimized_chunks": [], "summary": "Fallback"}
            
#             # Pipeline should handle OCR failure gracefully
#             result = await processor.process_pdf(str(pdf_path))
            
#             # Should still succeed with fallback
#             assert result["status"] == "success"
#             assert "warnings" in result  # Should log the OCR failure


# class TestMCPServerIntegration:
#     """Integration tests for MCP server functionality."""
    
#     @pytest.mark.asyncio
#     async def test_mcp_pdf_ingestion_flow(self, temp_dir):
#         """Test the complete MCP PDF ingestion flow."""
#         pdf_path = temp_dir / "mcp_test.pdf"
#         pdf_path.write_text("MCP integration test content")
        
#         request_data = {
#             "pdf_path": str(pdf_path),
#             "options": {
#                 "enable_ocr": True,
#                 "enable_llm_optimization": True,
#                 "chunk_size": 1024
#             }
#         }
        
#         # Mock the PDFProcessor but test the MCP tool integration
#         with patch('ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_ingest_to_graphrag.PDFProcessor') as mock_processor_class:
#             mock_processor = Mock()
#             mock_processor.process_pdf = AsyncMock(return_value={
#                 "status": "success",
#                 "document_id": "mcp_test_001",
#                 "chunks_created": 5,
#                 "entities_extracted": 8,
#                 "processing_time": "30.5s",
#                 "ipld_cid": "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
#             })
#             mock_processor_class.return_value = mock_processor
            
#             # Call the MCP tool
#             result = await pdf_ingest_to_graphrag(json.dumps(request_data))
            
#             # Verify MCP response format
#             assert "content" in result
#             assert len(result["content"]) == 1
#             assert result["content"][0]["type"] == "text"
            
#             # Verify response content
#             response_data = json.loads(result["content"][0]["text"])
#             assert response_data["status"] == "success"
#             assert response_data["document_id"] == "mcp_test_001"
#             assert response_data["chunks_created"] == 5
            
#             # Verify processor was called with correct arguments
#             mock_processor.process_pdf.assert_called_once()
#             call_args = mock_processor.process_pdf.call_args
#             assert call_args[0][0] == str(pdf_path)  # PDF path argument
    
#     @pytest.mark.asyncio
#     async def test_mcp_query_after_ingestion(self, temp_dir):
#         """Test querying after document ingestion via MCP."""
#         # First, simulate document ingestion
#         pdf_path = temp_dir / "query_test.pdf"
#         pdf_path.write_text("Document for querying test")
        
#         ingest_request = {
#             "pdf_path": str(pdf_path),
#             "document_id": "query_test_doc"
#         }
        
#         # Mock ingestion
#         with patch('ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_ingest_to_graphrag.PDFProcessor') as mock_processor:
#             mock_proc_instance = Mock()
#             mock_proc_instance.process_pdf = AsyncMock(return_value={
#                 "status": "success",
#                 "document_id": "query_test_doc"
#             })
#             mock_processor.return_value = mock_proc_instance
            
#             ingest_result = await pdf_ingest_to_graphrag(json.dumps(ingest_request))
#             ingest_data = json.loads(ingest_result["content"][0]["text"])
#             assert ingest_data["status"] == "success"
        
#         # Now test querying the ingested document
#         query_request = {
#             "query": "What is this document about?",
#             "query_type": "semantic_search",
#             "document_filter": ["query_test_doc"]
#         }
        
#         with patch('ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_query_corpus.QueryEngine') as mock_engine:
#             mock_engine_instance = Mock()
#             mock_engine_instance.query = AsyncMock(return_value={
#                 "results": [
#                     {
#                         "chunk_id": "chunk_001",
#                         "text": "This document discusses testing procedures",
#                         "score": 0.92,
#                         "document_id": "query_test_doc"
#                     }
#                 ],
#                 "total_found": 1,
#                 "query_time": "0.2s"
#             })
#             mock_engine.return_value = mock_engine_instance
            
#             query_result = await pdf_query_corpus(json.dumps(query_request))
#             query_data = json.loads(query_result["content"][0]["text"])
            
#             assert query_data["status"] == "success"
#             assert len(query_data["results"]) == 1
#             assert query_data["results"][0]["document_id"] == "query_test_doc"
    
#     @pytest.mark.asyncio
#     async def test_mcp_tool_chaining(self, temp_dir):
#         """Test chaining multiple MCP tools together."""
#         pdf_path = temp_dir / "chaining_test.pdf"
#         pdf_path.write_text("Tool chaining test document")
        
#         # Step 1: Ingest document
#         ingest_request = {
#             "pdf_path": str(pdf_path),
#             "document_id": "chain_test_doc"
#         }
        
#         with patch('ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_ingest_to_graphrag.PDFProcessor') as mock_processor:
#             mock_proc = Mock()
#             mock_proc.process_pdf = AsyncMock(return_value={
#                 "status": "success",
#                 "document_id": "chain_test_doc",
#                 "entities_extracted": 3
#             })
#             mock_processor.return_value = mock_proc
            
#             ingest_result = await pdf_ingest_to_graphrag(json.dumps(ingest_request))
#             assert json.loads(ingest_result["content"][0]["text"])["status"] == "success"
        
#         # Step 2: Extract entities from the ingested document
#         entity_request = {
#             "document_id": "chain_test_doc",
#             "entity_types": ["technology", "concept"]
#         }
        
#         with patch('ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_extract_entities.GraphRAGIntegrator') as mock_integrator:
#             mock_int = Mock()
#             mock_int.extract_entities = AsyncMock(return_value={
#                 "entities": [
#                     {"name": "Test Technology", "type": "technology", "confidence": 0.9}
#                 ]
#             })
#             mock_integrator.return_value = mock_int
            
#             from ipfs_datasets_py.mcp_server.tools.pdf_tools import pdf_extract_entities
#             entity_result = await pdf_extract_entities(json.dumps(entity_request))
#             entity_data = json.loads(entity_result["content"][0]["text"])
            
#             assert entity_data["status"] == "success"
#             assert len(entity_data["entities"]) == 1
        
#         # Step 3: Query for the extracted entities
#         query_request = {
#             "query": "Test Technology",
#             "query_type": "entity_search",
#             "document_filter": ["chain_test_doc"]
#         }
        
#         with patch('ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_query_corpus.QueryEngine') as mock_engine:
#             mock_eng = Mock()
#             mock_eng.query = AsyncMock(return_value={
#                 "results": [
#                     {
#                         "entity_name": "Test Technology",
#                         "mentions": 1,
#                         "document_id": "chain_test_doc"
#                     }
#                 ]
#             })
#             mock_engine.return_value = mock_eng
            
#             query_result = await pdf_query_corpus(json.dumps(query_request))
#             query_data = json.loads(query_result["content"][0]["text"])
            
#             assert query_data["status"] == "success"


# class TestPerformanceIntegration:
#     """Integration tests for performance and scalability."""
    
#     @pytest.mark.asyncio
#     async def test_concurrent_pdf_processing(self, temp_dir):
#         """Test concurrent processing of multiple PDFs."""
#         # Create multiple test PDF files
#         pdf_files = []
#         for i in range(3):  # Small number for fast tests
#             pdf_path = temp_dir / f"concurrent_{i}.pdf"
#             pdf_path.write_text(f"Content of document {i}")
#             pdf_files.append(pdf_path)
        
#         processor = PDFProcessor(enable_monitoring=False, enable_audit=False)
        
#         # Mock the processing to avoid heavy operations
#         with patch.object(processor, 'process_pdf') as mock_process:
#             mock_process.return_value = {
#                 "status": "success",
#                 "document_id": f"doc_{id(pdf_files)}",
#                 "processing_time": "1.0s"
#             }
            
#             # Process PDFs concurrently
#             tasks = [processor.process_pdf(str(pdf)) for pdf in pdf_files]
#             results = await asyncio.gather(*tasks)
            
#             # Verify all processed successfully
#             assert len(results) == 3
#             assert all(result["status"] == "success" for result in results)
#             assert mock_process.call_count == 3
    
#     @pytest.mark.asyncio
#     async def test_large_document_processing(self, temp_dir):
#         """Test processing of a large document (simulated)."""
#         # Create a large mock document
#         large_content = "Large document content. " * 1000  # Simulate large text
#         pdf_path = temp_dir / "large_doc.pdf"
#         pdf_path.write_text(large_content)
        
#         processor = PDFProcessor(enable_monitoring=False, enable_audit=False)
#         llm_optimizer = LLMOptimizer(max_chunk_size=512, chunk_overlap=100)
        
#         # Test chunking of large content
#         with patch('sentence_transformers.SentenceTransformer'):
#             chunks = await llm_optimizer.chunk_text(large_content)
            
#             # Should create multiple chunks for large content
#             assert len(chunks) > 1
            
#             # Verify chunk sizes are within limits
#             for chunk in chunks:
#                 assert len(chunk["text"]) <= llm_optimizer.max_chunk_size * 2  # Allow some flexibility
    
#     @pytest.mark.asyncio
#     async def test_memory_usage_monitoring(self, temp_dir):
#         """Test memory usage during processing."""
#         pdf_path = temp_dir / "memory_test.pdf"
#         pdf_path.write_text("Memory usage test content")
        
#         processor = PDFProcessor(enable_monitoring=False, enable_audit=False)
        
#         # Monitor memory usage (mock for testing)
#         initial_memory = 100  # MB (mocked)
        
#         with patch.object(processor, 'process_pdf') as mock_process:
#             mock_process.return_value = {
#                 "status": "success",
#                 "memory_used": "50MB",
#                 "peak_memory": "75MB"
#             }
            
#             result = await processor.process_pdf(str(pdf_path))
            
#             assert "memory_used" in result
#             assert result["status"] == "success"


# class TestErrorHandlingIntegration:
#     """Integration tests for error handling across components."""
    
#     @pytest.mark.asyncio
#     async def test_pipeline_resilience(self, temp_dir):
#         """Test pipeline resilience to component failures."""
#         pdf_path = temp_dir / "resilience_test.pdf"
#         pdf_path.write_text("Resilience test content")
        
#         processor = PDFProcessor(enable_monitoring=False, enable_audit=False)
        
#         # Test OCR failure but pipeline continues
#         with patch.object(processor, '_extract_text_and_images') as mock_extract, \
#              patch.object(processor, '_process_with_ocr') as mock_ocr, \
#              patch.object(processor, '_optimize_with_llm') as mock_llm:
            
#             mock_extract.return_value = {"text": "Basic text", "pages": []}
#             mock_ocr.side_effect = Exception("OCR service unavailable")
#             mock_llm.return_value = {"optimized_chunks": [], "summary": "Fallback"}
            
#             result = await processor.process_pdf(str(pdf_path))
            
#             # Should succeed with graceful degradation
#             assert result["status"] == "success"
#             assert "warnings" in result
    
#     @pytest.mark.asyncio
#     async def test_mcp_error_propagation(self):
#         """Test error propagation through MCP tools."""
#         invalid_request = '{"invalid": "json structure"}'
        
#         # Test that MCP tools handle invalid requests gracefully
#         result = await pdf_ingest_to_graphrag(invalid_request)
        
#         assert "content" in result
#         response_data = json.loads(result["content"][0]["text"])
#         assert response_data["status"] == "error"
#         assert "error" in response_data


# if __name__ == "__main__":
#     pytest.main([__file__, "-v", "--tb=short"])
