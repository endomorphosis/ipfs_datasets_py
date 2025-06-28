"""
Comprehensive Test Suite for PDF MCP Tools

This test suite validates all PDF processing MCP tools including
ingestion, querying, relationship analysis, batch processing,
entity extraction, LLM optimization, and cross-document analysis.
"""

import asyncio
import pytest
import tempfile
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import logging

# Configure logging for tests
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TestPDFMCPTools:
    """Test suite for PDF MCP tools."""
    
    @pytest.fixture
    def mock_pdf_content(self):
        """Mock PDF content for testing."""
        return {
            "text": "This is a sample PDF document with multiple pages. It contains research about artificial intelligence and machine learning. The document discusses various algorithms and their applications in real-world scenarios.",
            "pages": [
                {"page_number": 1, "text": "This is a sample PDF document with multiple pages."},
                {"page_number": 2, "text": "It contains research about artificial intelligence and machine learning."},
                {"page_number": 3, "text": "The document discusses various algorithms and their applications."}
            ],
            "metadata": {
                "title": "Sample Research Paper",
                "author": "Test Author",
                "pages": 3,
                "creation_date": "2024-01-01"
            },
            "structure": {
                "sections": [
                    {"title": "Introduction", "page": 1},
                    {"title": "Methodology", "page": 2},
                    {"title": "Results", "page": 3}
                ],
                "headings": ["Introduction", "Methodology", "Results"],
                "tables": [],
                "images": []
            }
        }
    
    @pytest.fixture
    def sample_pdf_file(self):
        """Create a temporary PDF file for testing."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            # Create a minimal PDF content (for testing we just need the file path)
            f.write(b"%PDF-1.4\n%Test PDF\nendobj\n%%EOF")
            return f.name
    
    @pytest.mark.asyncio
    async def test_pdf_ingest_to_graphrag_success(self, sample_pdf_file, mock_pdf_content):
        """Test successful PDF ingestion to GraphRAG."""
        from ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_ingest_to_graphrag import pdf_ingest_to_graphrag
        
        # Mock the PDF processor and its dependencies
        with patch('ipfs_datasets_py.pdf_processing.PDFProcessor') as mock_processor_class:
            mock_processor = AsyncMock()
            mock_processor_class.return_value = mock_processor
            
            # Mock the process_complete_pipeline method
            mock_processor.process_complete_pipeline.return_value = {
                "document_id": "test_doc_123",
                "ipld_cid": "QmTestCID123",
                "pipeline_stages": {
                    "decomposition": {"status": "success"},
                    "ipld_structuring": {"status": "success"},
                    "ocr_processing": {"status": "success"},
                    "llm_optimization": {"status": "success"},
                    "entity_extraction": {"status": "success"},
                    "vector_embedding": {"status": "success"},
                    "graphrag_integration": {"status": "success"},
                    "cross_document_analysis": {"status": "success"}
                },
                "processing_stats": {
                    "entities_extracted": 15,
                    "relationships_discovered": 8,
                    "embeddings_created": 25,
                    "total_time": 45.2,
                    "pages_processed": 3,
                    "text_length": 1500,
                    "images_processed": 0,
                    "chunks_created": 12
                }
            }
            
            # Mock the track_operation context manager
            with patch('ipfs_datasets_py.monitoring.track_operation') as mock_track:
                mock_track.return_value.__enter__.return_value = None
                mock_track.return_value.__exit__.return_value = None
                
                # Test the tool
                result = await pdf_ingest_to_graphrag(
                    pdf_source=sample_pdf_file,
                    metadata={"title": "Test Document"},
                    enable_ocr=True,
                    target_llm="gpt-4"
                )
                
                # Assertions
                assert result["status"] == "success"
                assert result["document_id"] == "test_doc_123"
                assert result["ipld_cid"] == "QmTestCID123"
                assert result["entities_added"] == 15
                assert result["relationships_added"] == 8
                assert result["vector_embeddings"] == 25
                assert result["processing_time"] == 45.2
                assert "Successfully ingested PDF" in result["message"]
                
                # Verify all pipeline stages succeeded
                stages = result["pipeline_stages"]
                assert all(stage["status"] == "success" for stage in stages.values())
                
                # Verify content summary
                content_summary = result["content_summary"]
                assert content_summary["pages_processed"] == 3
                assert content_summary["chunks_created"] == 12
    
    @pytest.mark.asyncio
    async def test_pdf_query_corpus_semantic_search(self):
        """Test semantic search in PDF corpus."""
        from ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_query_corpus import pdf_query_corpus
        
        # Mock the query engine
        with patch('ipfs_datasets_py.pdf_processing.QueryEngine') as mock_engine_class:
            mock_engine = AsyncMock()
            mock_engine_class.return_value = mock_engine
            
            # Mock semantic search results
            mock_engine.semantic_search.return_value = {
                "answer": "Artificial intelligence research focuses on machine learning algorithms and their practical applications.",
                "confidence": 0.85,
                "documents": [
                    {
                        "document_id": "doc_1",
                        "title": "AI Research Paper",
                        "score": 0.92,
                        "pages": [1, 2],
                        "excerpt": "This research explores AI applications...",
                        "metadata": {"author": "Dr. Smith"}
                    }
                ],
                "entities": ["artificial intelligence", "machine learning"],
                "relationships": [{"source": "AI", "target": "ML", "type": "includes"}],
                "processing_time": 2.5
            }
            
            with patch('ipfs_datasets_py.monitoring.track_operation') as mock_track:
                mock_track.return_value.__enter__.return_value = None
                mock_track.return_value.__exit__.return_value = None
                
                result = await pdf_query_corpus(
                    query="What is artificial intelligence research about?",
                    query_type="semantic",
                    max_documents=10,
                    confidence_threshold=0.7
                )
                
                assert result["status"] == "success"
                assert result["answer"] == "Artificial intelligence research focuses on machine learning algorithms and their practical applications."
                assert result["confidence_score"] == 0.85
                assert len(result["source_documents"]) == 1
                assert result["source_documents"][0]["document_id"] == "doc_1"
                assert result["entities_found"] == ["artificial intelligence", "machine learning"]
                assert len(result["relationships_found"]) == 1
    
    @pytest.mark.asyncio
    async def test_pdf_analyze_relationships_comprehensive(self):
        """Test comprehensive relationship analysis."""
        from ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_analyze_relationships import pdf_analyze_relationships
        
        # Mock the integrator and analyzer
        with patch('ipfs_datasets_py.pdf_processing.GraphRAGIntegrator') as mock_integrator_class, \
             patch('ipfs_datasets_py.graphrag.RelationshipAnalyzer') as mock_analyzer_class:
            
            mock_integrator = AsyncMock()
            mock_analyzer = AsyncMock()
            mock_integrator_class.return_value = mock_integrator
            mock_analyzer_class.return_value = mock_analyzer
            
            # Mock document info
            mock_integrator.get_document_info.return_value = {
                "document_id": "test_doc",
                "title": "Test Document",
                "pages": 5,
                "metadata": {}
            }
            
            # Mock relationship analysis results
            mock_analyzer.analyze_entity_relationships.return_value = {
                "entities": ["AI", "Machine Learning", "Deep Learning"],
                "relationships": [
                    {"source": "AI", "target": "Machine Learning", "type": "includes", "confidence": 0.9},
                    {"source": "Machine Learning", "target": "Deep Learning", "type": "includes", "confidence": 0.85}
                ],
                "processing_time": 3.2
            }
            
            mock_analyzer.analyze_citation_network.return_value = {
                "citations": [
                    {"source": "test_doc", "target": "ref_1", "type": "cites"}
                ],
                "processing_time": 1.5
            }
            
            mock_analyzer.analyze_thematic_relationships.return_value = {
                "themes": ["Artificial Intelligence", "Technology"],
                "relationships": [],
                "processing_time": 2.0
            }
            
            mock_analyzer.find_cross_document_relationships.return_value = {
                "relationships": [
                    {"source_doc": "test_doc", "target_doc": "other_doc", "strength": 0.8}
                ]
            }
            
            mock_analyzer.build_relationship_graph.return_value = {
                "nodes": 10,
                "edges": 15,
                "components": 2
            }
            
            with patch('ipfs_datasets_py.monitoring.track_operation') as mock_track:
                mock_track.return_value.__enter__.return_value = None
                mock_track.return_value.__exit__.return_value = None
                
                result = await pdf_analyze_relationships(
                    document_id="test_doc",
                    analysis_type="comprehensive",
                    include_cross_document=True,
                    min_confidence=0.6
                )
                
                assert result["status"] == "success"
                assert result["document_info"]["document_id"] == "test_doc"
                assert len(result["entity_relationships"]["relationships"]) == 2
                assert len(result["citation_network"]["citations"]) == 1
                assert len(result["cross_document_relationships"]) == 1
                assert result["analysis_summary"]["total_relationships"] >= 3
    
    @pytest.mark.asyncio
    async def test_pdf_batch_process_multiple_documents(self, sample_pdf_file):
        """Test batch processing of multiple PDF documents."""
        from ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_batch_process import pdf_batch_process
        
        # Create additional sample files
        pdf_sources = [sample_pdf_file, sample_pdf_file, sample_pdf_file]  # Use same file 3 times for testing
        
        with patch('ipfs_datasets_py.pdf_processing.BatchProcessor') as mock_processor_class:
            mock_processor = AsyncMock()
            mock_processor_class.return_value = mock_processor
            
            # Mock batch processing results
            mock_processor.process_batch.return_value = {
                "document_results": [
                    {
                        "status": "success",
                        "document_id": f"doc_{i}",
                        "source_path": sample_pdf_file,
                        "ipld_cid": f"QmTest{i}",
                        "processing_time": 15.0 + i,
                        "entities_extracted": 10 + i,
                        "relationships_discovered": 5 + i,
                        "vector_embeddings": 20 + i,
                        "pages_processed": 3,
                        "chunks_created": 8 + i
                    }
                    for i in range(3)
                ],
                "cross_document_analysis": {
                    "relationships": [
                        {"source": "doc_0", "target": "doc_1", "strength": 0.8},
                        {"source": "doc_1", "target": "doc_2", "strength": 0.7}
                    ],
                    "entity_clusters": [
                        {"entities": ["AI", "ML"], "documents": ["doc_0", "doc_1"]}
                    ],
                    "thematic_connections": [
                        {"theme": "Technology", "documents": ["doc_0", "doc_1", "doc_2"]}
                    ]
                },
                "total_processing_time": 48.0,
                "average_processing_time": 16.0,
                "parallel_efficiency": 0.85,
                "peak_memory_usage": "2.5GB"
            }
            
            with patch('ipfs_datasets_py.monitoring.ProgressTracker'), \
                 patch('ipfs_datasets_py.monitoring.track_operation') as mock_track:
                
                mock_track.return_value.__enter__.return_value = None
                mock_track.return_value.__exit__.return_value = None
                
                result = await pdf_batch_process(
                    pdf_sources=pdf_sources,
                    batch_size=2,
                    parallel_workers=2,
                    enable_cross_document=True,
                    output_format="detailed"
                )
                
                assert result["status"] == "success"
                assert result["batch_summary"]["total_documents"] == 3
                assert result["batch_summary"]["successfully_processed"] == 3
                assert result["batch_summary"]["failed_processing"] == 0
                assert result["batch_summary"]["success_rate"] == 100.0
                assert len(result["processed_documents"]) == 3
                assert len(result["failed_documents"]) == 0
                assert result["cross_document_analysis"]["cross_document_relationships"] == 2
                assert result["performance_metrics"]["total_processing_time"] == 48.0
    
    @pytest.mark.asyncio
    async def test_pdf_extract_entities_with_custom_patterns(self, sample_pdf_file):
        """Test entity extraction with custom patterns."""
        from ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_extract_entities import pdf_extract_entities
        
        with patch('ipfs_datasets_py.pdf_processing.PDFProcessor') as mock_processor_class, \
             patch('ipfs_datasets_py.nlp.EntityExtractor') as mock_extractor_class:
            
            mock_processor = AsyncMock()
            mock_extractor = AsyncMock()
            mock_processor_class.return_value = mock_processor
            mock_extractor_class.return_value = mock_extractor
            
            # Mock content extraction
            mock_processor.extract_text_content.return_value = {
                "status": "success",
                "content": {
                    "text": "Dr. John Smith from MIT published research on artificial intelligence in 2024.",
                    "pages": [{"page_number": 1, "text": "Dr. John Smith from MIT..."}]
                },
                "pages": 1
            }
            
            # Mock entity extraction
            mock_extractor.extract_entities.return_value = {
                "entities": [
                    {
                        "text": "Dr. John Smith",
                        "type": "PERSON",
                        "confidence": 0.95,
                        "start_char": 0,
                        "end_char": 13,
                        "page_number": 1,
                        "context": "Dr. John Smith from MIT published research",
                        "normalized_value": "John Smith"
                    },
                    {
                        "text": "MIT",
                        "type": "ORGANIZATION",
                        "confidence": 0.92,
                        "start_char": 19,
                        "end_char": 22,
                        "page_number": 1,
                        "context": "John Smith from MIT published",
                        "normalized_value": "Massachusetts Institute of Technology"
                    },
                    {
                        "text": "2024",
                        "type": "DATE",
                        "confidence": 0.98,
                        "start_char": 70,
                        "end_char": 74,
                        "page_number": 1,
                        "context": "published research on artificial intelligence in 2024",
                        "normalized_value": "2024"
                    }
                ],
                "processing_time": 2.1
            }
            
            with patch('ipfs_datasets_py.nlp.RelationshipExtractor') as mock_rel_extractor:
                mock_rel_extractor.return_value.extract_relationships.return_value = {
                    "relationships": [
                        {
                            "source": "John Smith",
                            "target": "MIT",
                            "type": "affiliated_with",
                            "confidence": 0.9
                        }
                    ]
                }
                
                with patch('ipfs_datasets_py.monitoring.track_operation') as mock_track:
                    mock_track.return_value.__enter__.return_value = None
                    mock_track.return_value.__exit__.return_value = None
                    
                    result = await pdf_extract_entities(
                        pdf_source=sample_pdf_file,
                        entity_types=["PERSON", "ORGANIZATION", "DATE"],
                        extraction_method="hybrid",
                        confidence_threshold=0.8,
                        include_relationships=True,
                        custom_patterns={"EMAIL": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"}
                    )
                    
                    assert result["status"] == "success"
                    assert len(result["entities_extracted"]) == 3
                    assert len(result["entity_relationships"]) == 1
                    
                    # Check entity types summary
                    summary = result["entity_summary"]
                    assert "PERSON" in summary
                    assert "ORGANIZATION" in summary
                    assert "DATE" in summary
                    assert summary["PERSON"]["count"] == 1
                    assert summary["ORGANIZATION"]["count"] == 1
                    assert summary["DATE"]["count"] == 1
                    
                    # Check confidence analysis
                    confidence = result["confidence_analysis"]
                    assert confidence["mean_confidence"] > 0.9
                    assert confidence["high_confidence_count"] == 3
    
    @pytest.mark.asyncio
    async def test_pdf_optimize_for_llm_with_chunking(self, sample_pdf_file):
        """Test PDF optimization for LLM with advanced chunking."""
        from ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_optimize_for_llm import pdf_optimize_for_llm
        
        with patch('ipfs_datasets_py.pdf_processing.LLMOptimizer') as mock_optimizer_class, \
             patch('ipfs_datasets_py.pdf_processing.PDFProcessor') as mock_processor_class:
            
            mock_optimizer = AsyncMock()
            mock_processor = AsyncMock()
            mock_optimizer_class.return_value = mock_optimizer
            mock_processor_class.return_value = mock_processor
            
            # Mock content extraction
            mock_processor.extract_structured_content.return_value = {
                "status": "success",
                "content": {
                    "text": "This is a long research document about artificial intelligence. " * 100,  # Simulate long content
                    "structure": {
                        "sections": [{"title": "Introduction", "page": 1}],
                        "headings": ["Introduction"],
                        "tables": [],
                        "images": []
                    },
                    "metadata": {"title": "AI Research"}
                },
                "pages": 5,
                "structure": {}
            }
            
            # Mock optimization results
            mock_optimizer.optimize_document.return_value = {
                "optimized_content": "Optimized content for LLM consumption...",
                "compression_ratio": 0.85,
                "semantic_coherence": 0.92,
                "complexity_score": 0.7,
                "structure_quality": "high",
                "estimated_tokens": 3500,
                "token_efficiency": 0.88,
                "processing_time": 8.5
            }
            
            # Mock chunking results
            with patch('ipfs_datasets_py.nlp.ChunkOptimizer') as mock_chunk_optimizer:
                mock_chunk_optimizer.return_value.create_optimized_chunks.return_value = {
                    "chunks": [
                        {
                            "content": f"Chunk {i} content optimized for GPT-4...",
                            "token_count": 350 + i * 10,
                            "type": "content",
                            "page_range": [i + 1],
                            "structure_level": 1,
                            "semantic_score": 0.85 + i * 0.02,
                            "importance_score": 0.8 + i * 0.01,
                            "metadata": {"chunk_type": "semantic"}
                        }
                        for i in range(10)
                    ],
                    "overlap_efficiency": 0.92
                }
                
                # Mock summarization
                with patch('ipfs_datasets_py.nlp.SummarizationEngine') as mock_summarizer:
                    mock_summarizer.return_value.summarize_document.return_value = {
                        "summary": "This research paper explores artificial intelligence methodologies and applications."
                    }
                    
                    # Mock LLM recommendations
                    mock_optimizer.get_llm_recommendations.return_value = {
                        "batch_size": 3,
                        "temperature": 0.7,
                        "max_tokens": 4000,
                        "preprocessing_suggestions": ["normalize_whitespace", "remove_headers"]
                    }
                    
                    mock_optimizer.estimate_processing_cost.return_value = {
                        "estimated_cost_usd": 0.07,
                        "token_count": 3500,
                        "model": "gpt-4"
                    }
                    
                    with patch('ipfs_datasets_py.monitoring.track_operation') as mock_track:
                        mock_track.return_value.__enter__.return_value = None
                        mock_track.return_value.__exit__.return_value = None
                        
                        result = await pdf_optimize_for_llm(
                            pdf_source=sample_pdf_file,
                            target_llm="gpt-4",
                            chunk_strategy="semantic",
                            max_chunk_size=4000,
                            overlap_size=200,
                            enable_summarization=True,
                            preserve_structure=True
                        )
                        
                        assert result["status"] == "success"
                        assert len(result["optimized_chunks"]) == 10
                        assert result["document_summary"] == "This research paper explores artificial intelligence methodologies and applications."
                        assert result["optimization_metrics"]["compression_ratio"] == 0.85
                        assert result["optimization_metrics"]["chunks_created"] == 10
                        assert result["llm_recommendations"]["batch_size"] == 3
                        assert result["token_analysis"]["estimated_total_tokens"] == 3500
                        assert result["token_analysis"]["cost_estimate"]["estimated_cost_usd"] == 0.07
    
    @pytest.mark.asyncio
    async def test_pdf_cross_document_analysis_corpus_wide(self):
        """Test corpus-wide cross-document analysis."""
        from ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_cross_document_analysis import pdf_cross_document_analysis
        
        with patch('ipfs_datasets_py.pdf_processing.GraphRAGIntegrator') as mock_integrator_class, \
             patch('ipfs_datasets_py.analysis.CrossDocumentAnalyzer') as mock_analyzer_class:
            
            mock_integrator = AsyncMock()
            mock_analyzer = AsyncMock()
            mock_integrator_class.return_value = mock_integrator
            mock_analyzer_class.return_value = mock_analyzer
            
            # Mock document corpus
            mock_integrator.get_all_documents.return_value = [
                {"document_id": f"doc_{i}", "title": f"Document {i}", "date": f"2024-0{i+1}-01", "type": "research", "pages": 10}
                for i in range(5)
            ]
            
            # Mock analysis results
            mock_analyzer.analyze_entity_connections.return_value = {
                "connections": [
                    {"entities": ["AI", "ML"], "documents": ["doc_0", "doc_1"], "strength": 0.9},
                    {"entities": ["Deep Learning", "Neural Networks"], "documents": ["doc_1", "doc_2"], "strength": 0.85}
                ]
            }
            
            mock_analyzer.analyze_thematic_relationships.return_value = {
                "clusters": [
                    {"theme": "Machine Learning", "documents": ["doc_0", "doc_1", "doc_2"]},
                    {"theme": "Computer Vision", "documents": ["doc_2", "doc_3"]}
                ]
            }
            
            mock_analyzer.build_citation_networks.return_value = {
                "networks": [
                    {"source": "doc_0", "target": "doc_1", "citation_type": "direct"},
                    {"source": "doc_1", "target": "doc_2", "citation_type": "indirect"}
                ]
            }
            
            mock_analyzer.calculate_document_influence.return_value = {
                "document_scores": [
                    {"document_id": "doc_0", "title": "Document 0", "influence_score": 0.95},
                    {"document_id": "doc_1", "title": "Document 1", "influence_score": 0.88}
                ]
            }
            
            mock_analyzer.discover_knowledge_connections.return_value = {
                "discoveries": [
                    {"connection": "Novel AI-Ethics relationship", "novelty_score": 0.92},
                    {"connection": "Cross-domain ML application", "novelty_score": 0.87}
                ]
            }
            
            # Mock temporal analysis
            with patch('ipfs_datasets_py.analysis.TemporalAnalyzer') as mock_temporal:
                mock_temporal.return_value.analyze_temporal_evolution.return_value = {
                    "evolution": [
                        {"year": 2024, "theme": "AI", "strength": 0.9},
                        {"year": 2024, "theme": "ML", "strength": 0.85}
                    ]
                }
                
                with patch('ipfs_datasets_py.monitoring.track_operation') as mock_track:
                    mock_track.return_value.__enter__.return_value = None
                    mock_track.return_value.__exit__.return_value = None
                    
                    result = await pdf_cross_document_analysis(
                        document_ids=None,  # Analyze entire corpus
                        analysis_types=["entities", "themes", "citations", "influence"],
                        similarity_threshold=0.75,
                        temporal_analysis=True,
                        include_visualizations=False,
                        output_format="detailed"
                    )
                    
                    assert result["status"] == "success"
                    assert result["corpus_info"]["total_documents"] == 5
                    assert len(result["entity_connections"]) == 2
                    assert len(result["thematic_clusters"]) == 2
                    assert len(result["citation_networks"]) == 2
                    assert len(result["influence_analysis"]["document_scores"]) == 2
                    assert result["analysis_summary"]["documents_analyzed"] == 5
                    assert result["analysis_summary"]["total_entity_connections"] == 2
                    assert result["analysis_summary"]["most_influential_documents"][0]["document_id"] == "doc_0"

    @pytest.mark.asyncio
    async def test_error_handling_file_not_found(self):
        """Test error handling for non-existent PDF files."""
        from ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_ingest_to_graphrag import pdf_ingest_to_graphrag
        
        result = await pdf_ingest_to_graphrag(
            pdf_source="/non/existent/file.pdf"
        )
        
        assert result["status"] == "error"
        assert "not found" in result["message"]
    
    @pytest.mark.asyncio
    async def test_error_handling_invalid_parameters(self):
        """Test error handling for invalid parameters."""
        from ipfs_datasets_py.mcp_server.tools.pdf_tools.pdf_query_corpus import pdf_query_corpus
        
        # Test invalid query type
        result = await pdf_query_corpus(
            query="test query",
            query_type="invalid_type"
        )
        
        assert result["status"] == "error"
        assert "Invalid query type" in result["message"]
        
        # Test invalid confidence threshold
        result = await pdf_query_corpus(
            query="test query",
            confidence_threshold=1.5  # Invalid: > 1.0
        )
        
        assert result["status"] == "error"
        assert "confidence_threshold must be between 0.0 and 1.0" in result["message"]


if __name__ == "__main__":
    # Run tests
    import pytest
    pytest.main([__file__, "-v"])
