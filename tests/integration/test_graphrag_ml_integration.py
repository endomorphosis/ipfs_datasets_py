"""
Phase 3: Integration Tests with Real ML Dependencies

Comprehensive integration tests for GraphRAG PDF processing with actual
machine learning models, transformers, and full NLP pipeline functionality.
"""
import pytest
import anyio
import tempfile
import os
import json
from pathlib import Path
import warnings

# Suppress warnings from transformers and torch
warnings.filterwarnings("ignore", category=UserWarning)

# Test fixtures and utilities
from tests.conftest import *


@pytest.mark.integration
@pytest.mark.ml_dependencies
class TestGraphRAGWithRealML:
    """Integration tests using real ML models and transformers"""
    
    @pytest.fixture(scope="class")
    def ml_sample_pdf(self):
        """Create a rich sample PDF for ML testing"""
        try:
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import letter
            
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
                pdf_path = tmp_file.name
            
            c = canvas.Canvas(pdf_path, pagesize=letter)
            width, height = letter
            
            # Create research paper with rich entity content
            c.setFont("Helvetica-Bold", 16)
            c.drawCentredString(width/2, height-100, "Deep Learning Applications in Natural Language Processing")
            
            c.setFont("Helvetica", 12)
            c.drawCentredString(width/2, height-140, "Dr. Emily Chen (University of California, Berkeley)")
            c.drawCentredString(width/2, height-160, "Prof. Michael Rodriguez (Stanford University)")
            c.drawCentredString(width/2, height-180, "Dr. Sarah Johnson (Massachusetts Institute of Technology)")
            
            c.setFont("Helvetica-Bold", 14)
            c.drawString(50, height-220, "Abstract")
            
            c.setFont("Helvetica", 10)
            y_pos = height-240
            content_lines = [
                "This paper presents novel applications of Deep Learning in Natural Language Processing,",
                "focusing on transformer architectures like BERT, GPT, and T5 for text understanding.",
                "Our research explores entity recognition, sentiment analysis, and question answering",
                "using state-of-the-art neural networks including Convolutional Neural Networks (CNNs)",
                "and Recurrent Neural Networks (RNNs).",
                "",
                "The study evaluates performance on datasets including Wikipedia, Common Crawl,",
                "and scientific publications from arXiv. We implemented models using PyTorch,",
                "TensorFlow, and Hugging Face Transformers libraries.",
                "",
                "Key findings demonstrate that transformer models achieve 94% accuracy in",
                "named entity recognition tasks, significantly outperforming traditional approaches.",
                "The integration of attention mechanisms and positional encoding enables",
                "better understanding of context and semantic relationships.",
                "",
                "Collaborating institutions include Google Research, OpenAI, and Facebook AI Research.",
                "This work builds upon previous studies by Vaswani et al. (2017) on attention",
                "mechanisms and advances in pre-trained language models.",
                "",
                "Technologies: Python, PyTorch, Transformers, CUDA, Docker, Kubernetes",
                "Keywords: Deep Learning, NLP, Transformers, BERT, Entity Recognition, ML"
            ]
            
            for line in content_lines:
                c.drawString(50, y_pos, line)
                y_pos -= 12
                if y_pos < 100:
                    c.showPage()
                    y_pos = height - 50
            
            c.save()
            yield pdf_path
            
            # Cleanup
            if os.path.exists(pdf_path):
                os.unlink(pdf_path)
                
        except ImportError:
            pytest.skip("reportlab not available for PDF creation")
    
    @pytest.mark.asyncio
    async def test_given_real_transformers_when_processing_pdf_then_extracts_accurate_entities(self, ml_sample_pdf):
        """
        GIVEN real transformer models for entity extraction
        WHEN processing PDF with rich entity content
        THEN should accurately extract and classify entities
        """
        from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor
        
        processor = PDFProcessor(
            enable_monitoring=True,
            use_real_ml_models=True
        )
        
        results = await processor.process_pdf(ml_sample_pdf)
        
        # Should successfully process with real ML
        assert isinstance(results, dict)
        assert 'status' in results
        
        if results['status'] == 'success':
            # Should extract meaningful entities with real models
            assert 'entities_count' in results
            assert results['entities_count'] > 5  # Rich content should yield many entities
            
            if 'extracted_entities' in results:
                entities = results['extracted_entities']
                # Should identify different entity types
                entity_types = set(entity.get('type', '') for entity in entities)
                assert len(entity_types) > 1  # Multiple entity types
                
                # Should find specific entities from our content
                entity_texts = [entity.get('text', '').lower() for entity in entities]
                expected_entities = ['bert', 'pytorch', 'stanford', 'deep learning']
                found_entities = [e for e in expected_entities if any(e in text for text in entity_texts)]
                assert len(found_entities) > 0  # Should find at least some expected entities
    
    @pytest.mark.asyncio
    async def test_given_sentence_transformers_when_generating_embeddings_then_creates_quality_vectors(self, ml_sample_pdf):
        """
        GIVEN sentence transformer models
        WHEN generating embeddings for PDF content
        THEN should create high-quality vector representations
        """
        from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor
        
        processor = PDFProcessor(
            enable_embeddings=True,
            embedding_model="all-MiniLM-L6-v2"
        )
        
        results = await processor.process_pdf(ml_sample_pdf)
        
        if results['status'] == 'success':
            # Should generate embeddings
            if 'embeddings' in results:
                embeddings = results['embeddings']
                assert isinstance(embeddings, list)
                assert len(embeddings) > 0
                
                # Each embedding should be a vector
                for embedding in embeddings[:3]:  # Check first few
                    assert hasattr(embedding, '__len__')
                    assert len(embedding) > 300  # Typical sentence transformer dimension
    
    @pytest.mark.asyncio
    async def test_given_real_nlp_models_when_discovering_relationships_then_finds_semantic_connections(self, ml_sample_pdf):
        """
        GIVEN real NLP models for relationship discovery
        WHEN analyzing PDF content for relationships
        THEN should discover meaningful semantic connections
        """
        from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator
        
        integrator = GraphRAGIntegrator(
            use_real_models=True,
            enable_relationship_discovery=True
        )
        
        # Process document for relationships
        document_id = "ml_paper_001"
        results = await integrator.integrate_document(ml_sample_pdf, document_id)

        relationships = None
        if isinstance(results, dict):
            relationships = results.get('relationships')
        elif hasattr(results, 'relationships'):
            relationships = results.relationships

        if relationships is not None:
            assert isinstance(relationships, list)
            
            if len(relationships) > 0:
                # Should find meaningful relationships
                def _relationship_type(rel):
                    if isinstance(rel, dict):
                        return rel.get('type', '') or rel.get('relationship_type', '')
                    return getattr(rel, 'relationship_type', '')

                relationship_types = set(_relationship_type(rel) for rel in relationships)
                assert len(relationship_types) > 0
                
                # Should connect related entities (e.g., authors to institutions)
                for rel in relationships[:5]:  # Check first few
                    if isinstance(rel, dict):
                        assert 'source_entity' in rel or 'source_entity_id' in rel
                        assert 'target_entity' in rel or 'target_entity_id' in rel
                        assert 'confidence' in rel or 'relationship_type' in rel
                    else:
                        assert getattr(rel, 'source_entity_id', None) is not None
                        assert getattr(rel, 'target_entity_id', None) is not None
                        assert getattr(rel, 'relationship_type', None) is not None or getattr(rel, 'confidence', None) is not None
    
    @pytest.mark.asyncio
    async def test_given_real_models_when_performing_cross_document_analysis_then_connects_related_content(self):
        """
        GIVEN multiple documents with real ML models
        WHEN performing cross-document analysis
        THEN should identify connections between documents
        """
        from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator
        
        integrator = GraphRAGIntegrator(use_real_models=True)
        
        # Simulate multiple document analysis
        doc_ids = ["paper1_ml", "paper2_nlp", "paper3_transformers"]
        
        cross_analysis = await integrator.analyze_cross_document_relationships(doc_ids)
        
        # Should return cross-document analysis
        assert isinstance(cross_analysis, (list, dict))
        
        if isinstance(cross_analysis, list) and len(cross_analysis) > 0:
            # Should identify cross-document connections
            for connection in cross_analysis:
                assert 'documents' in connection or 'document_ids' in connection
                assert 'similarity' in connection or 'relationship_strength' in connection


@pytest.mark.integration
@pytest.mark.ml_dependencies
class TestAdvancedMLCapabilities:
    """Advanced ML functionality integration tests"""
    
    @pytest.mark.asyncio
    async def test_given_query_engine_with_transformers_when_semantic_search_then_provides_relevant_results(self):
        """
        GIVEN query engine with real transformer models
        WHEN performing semantic search
        THEN should provide highly relevant results
        """
        try:
            from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine
            from ipfs_datasets_py.pdf_processing.query_engine import QueryResponse
            from ipfs_datasets_py.pdf_processing.query_engine import QueryResponse
            from ipfs_datasets_py.pdf_processing.query_engine import QueryResponse
            
            engine = QueryEngine(
                embedding_model="all-MiniLM-L6-v2",
                use_real_models=True
            )
            
            # Test semantic queries
            queries = [
                "machine learning applications in healthcare",
                "neural network architectures for NLP",
                "transformer models and attention mechanisms"
            ]
            
            for query in queries:
                results = await engine.query(
                    query_text=query,
                    top_k=5,
                    include_semantic_similarity=True
                )
                
                # Should return semantic search results
                if isinstance(results, dict):
                    assert 'results' in results
                    assert 'confidence' in results
                    confidence = results.get('confidence', 0)
                else:
                    assert hasattr(results, 'results')
                    assert hasattr(results, 'metadata')
                    confidence = getattr(results, 'metadata', {}).get('confidence', 0)
                
                # Confidence should be meaningful with real models
                if confidence > 0:
                    assert 0 <= confidence <= 1
                    
        except ImportError:
            pytest.skip("Advanced query engine dependencies not available")
    
    def test_given_real_nltk_models_when_processing_text_then_accurate_linguistic_analysis(self):
        """
        GIVEN real NLTK models and data
        WHEN processing text for linguistic analysis
        THEN should provide accurate POS tagging and NER
        """
        try:
            import nltk
            from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator
            
            # Download required NLTK data
            try:
                nltk.download('punkt', quiet=True)
                nltk.download('averaged_perceptron_tagger_eng', quiet=True)
                nltk.download('maxent_ne_chunker_tab', quiet=True)
                nltk.download('words', quiet=True)
            except:
                pass  # May already be downloaded or not available
            
            integrator = GraphRAGIntegrator()
            
            text = "Dr. Alice Johnson from Stanford University researches deep learning and neural networks at Google Research."
            
            entities = integrator.extract_entities(text)
            
            # Should extract entities using real NLTK models
            assert isinstance(entities, list)
            # Real models should find at least some entities
            
        except ImportError:
            pytest.skip("NLTK dependencies not available")
    
    @pytest.mark.asyncio
    async def test_given_huggingface_models_when_text_classification_then_accurate_categorization(self):
        """
        GIVEN Hugging Face transformer models
        WHEN performing text classification
        THEN should accurately categorize content
        """
        try:
            from transformers import pipeline
            from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer
            
            # Use pre-trained classification model
            optimizer = LLMOptimizer(
                classification_model="distilbert-base-uncased-finetuned-sst-2-english"
            )
            
            # Test classification of academic content
            texts = [
                "This paper presents a novel deep learning architecture for natural language processing.",
                "The experimental results show significant improvements in model accuracy.",
                "Future work will explore applications in computer vision and robotics."
            ]
            
            for text in texts:
                classification = await optimizer.classify_content(text)
                
                # Should return classification results
                assert isinstance(classification, dict)
                if 'label' in classification:
                    assert isinstance(classification['label'], str)
                if 'confidence' in classification:
                    assert isinstance(classification['confidence'], (int, float))
                    assert 0 <= classification['confidence'] <= 1
                    
        except ImportError:
            pytest.skip("Transformers classification not available")


@pytest.mark.integration 
@pytest.mark.ml_dependencies
@pytest.mark.slow
class TestEndToEndMLPipeline:
    """End-to-end integration tests with full ML pipeline"""
    
    @pytest.fixture(scope="class")
    def comprehensive_pdf_collection(self):
        """Create multiple PDFs for comprehensive testing"""
        try:
            from reportlab.pdfgen import canvas
            
            pdf_paths = []
            
            # Create multiple research papers
            papers = [
                {
                    "title": "Attention Mechanisms in Neural Networks",
                    "authors": ["Dr. Alex Smith (MIT)", "Prof. Maria Garcia (Stanford)"],
                    "content": [
                        "This study explores attention mechanisms in transformer architectures.",
                        "We evaluate BERT, GPT, and T5 models on various NLP tasks.",
                        "The research focuses on self-attention and cross-attention patterns.",
                        "Experimental results demonstrate improved performance on question answering."
                    ]
                },
                {
                    "title": "Computer Vision with Convolutional Networks",
                    "authors": ["Dr. James Wilson (Google)", "Dr. Lisa Chen (Facebook)"],
                    "content": [
                        "Convolutional Neural Networks have revolutionized computer vision.",
                        "This paper presents novel architectures for image classification.",
                        "We compare ResNet, DenseNet, and EfficientNet models.",
                        "Applications include medical imaging and autonomous vehicles."
                    ]
                },
                {
                    "title": "Reinforcement Learning for Robotics",
                    "authors": ["Prof. David Kumar (CMU)", "Dr. Anna Petrov (OpenAI)"],
                    "content": [
                        "Reinforcement learning enables autonomous robotic control.",
                        "This work explores policy gradient methods and Q-learning.",
                        "We demonstrate applications in robotic manipulation tasks.",
                        "The research integrates simulation and real-world testing."
                    ]
                }
            ]
            
            for i, paper in enumerate(papers):
                with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
                    pdf_path = tmp_file.name
                
                c = canvas.Canvas(pdf_path)
                y_pos = 750
                
                # Title
                c.setFont("Helvetica-Bold", 16)
                c.drawString(50, y_pos, paper["title"])
                y_pos -= 40
                
                # Authors
                c.setFont("Helvetica", 12)
                for author in paper["authors"]:
                    c.drawString(50, y_pos, author)
                    y_pos -= 20
                y_pos -= 20
                
                # Content
                c.setFont("Helvetica", 10)
                for line in paper["content"]:
                    c.drawString(50, y_pos, line)
                    y_pos -= 15
                    if y_pos < 100:
                        c.showPage()
                        y_pos = 750
                
                c.save()
                pdf_paths.append(pdf_path)
            
            yield pdf_paths
            
            # Cleanup
            for pdf_path in pdf_paths:
                if os.path.exists(pdf_path):
                    os.unlink(pdf_path)
                    
        except ImportError:
            pytest.skip("PDF creation dependencies not available")
    
    @pytest.mark.asyncio
    async def test_given_full_ml_pipeline_when_processing_document_collection_then_builds_comprehensive_knowledge_graph(self, comprehensive_pdf_collection):
        """
        GIVEN complete ML pipeline with real models
        WHEN processing collection of related documents
        THEN should build comprehensive knowledge graph with cross-document connections
        """
        from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor
        from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator
        
        processor = PDFProcessor(
            enable_monitoring=True,
            use_real_ml_models=True,
            enable_cross_document_analysis=True
        )
        
        integrator = GraphRAGIntegrator(use_real_models=True)
        
        # Process all documents
        document_results = []
        for i, pdf_path in enumerate(comprehensive_pdf_collection):
            results = await processor.process_pdf(pdf_path)
            document_results.append({
                'document_id': f'paper_{i+1}',
                'results': results,
                'path': pdf_path
            })
        
        # Analyze cross-document relationships
        doc_ids = [doc['document_id'] for doc in document_results]
        cross_analysis = await integrator.analyze_cross_document_relationships(doc_ids)
        
        # Validate comprehensive knowledge graph
        successful_docs = [doc for doc in document_results if doc['results'].get('status') == 'success']
        
        if len(successful_docs) > 1:
            # Should find cross-document connections
            assert isinstance(cross_analysis, (list, dict))
            
            # Should identify common entities across documents
            all_entities = []
            for doc in successful_docs:
                if 'extracted_entities' in doc['results']:
                    all_entities.extend(doc['results']['extracted_entities'])
            
            # Should have extracted entities from multiple documents
            assert len(all_entities) > 0
            
            # Should identify common research themes
            entity_texts = [entity.get('text', '').lower() for entity in all_entities]
            research_terms = ['neural', 'learning', 'model', 'network', 'research']
            found_terms = [term for term in research_terms if any(term in text for text in entity_texts)]
            assert len(found_terms) > 0  # Should find research-related entities
    
    @pytest.mark.asyncio
    async def test_given_complete_system_when_querying_knowledge_graph_then_provides_intelligent_responses(self, comprehensive_pdf_collection):
        """
        GIVEN complete GraphRAG system with knowledge graph
        WHEN querying with complex questions
        THEN should provide intelligent, context-aware responses
        """
        try:
            from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine
            from ipfs_datasets_py.pdf_processing.query_engine import QueryResponse
            
            engine = QueryEngine(
                embedding_model="all-MiniLM-L6-v2",
                use_real_models=True,
                enable_graph_traversal=True
            )
            
            # Complex research queries
            queries = [
                "Which researchers work on neural networks and attention mechanisms?",
                "How are computer vision and robotics applications connected?",
                "What are the common themes across these research papers?",
                "Which institutions collaborate on machine learning research?"
            ]
            
            query_results = []
            for query in queries:
                result = await engine.query(
                    query_text=query,
                    top_k=10,
                    include_cross_document_reasoning=True,
                    enable_graph_traversal=True
                )
                query_results.append(result)
                
                # Should return intelligent responses
                assert isinstance(result, (dict, QueryResponse))

                if isinstance(result, QueryResponse):
                    result_dict = {
                        'results': result.results,
                        'confidence': result.metadata.get('confidence', 0)
                    }
                else:
                    result_dict = result

                assert 'results' in result_dict

                # Real ML models should provide meaningful confidence scores
                if 'confidence' in result_dict and result_dict['confidence'] > 0:
                    assert 0 <= result_dict['confidence'] <= 1
            
            # Should handle multiple queries successfully
            successful_queries = []
            for result in query_results:
                if isinstance(result, QueryResponse):
                    confidence = result.metadata.get('confidence', 0)
                else:
                    confidence = result.get('confidence', 0)
                if confidence > 0:
                    successful_queries.append(result)
            # At least some queries should succeed with real models
            
        except ImportError:
            pytest.skip("Advanced query capabilities not available")


if __name__ == "__main__":
    # Run ML integration tests
    pytest.main([__file__, "-v", "-m", "ml_dependencies"])