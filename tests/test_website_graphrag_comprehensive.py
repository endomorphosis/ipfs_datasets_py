"""
Comprehensive test suite for Website GraphRAG Processing

This test suite validates the complete website GraphRAG processing pipeline
including web archiving, content discovery, multi-modal processing,
knowledge graph extraction, and GraphRAG system functionality.

Test Coverage:
- Unit tests for each component
- Integration tests for complete pipeline  
- Performance benchmarks
- Error handling and edge cases
"""

import pytest
import anyio
import tempfile
import shutil
import json
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from datetime import datetime
from typing import Dict, List, Any

import numpy as np

# Import components under test
from ipfs_datasets_py.website_graphrag_processor import WebsiteGraphRAGProcessor, WebsiteProcessingConfig
from ipfs_datasets_py.content_discovery import ContentDiscoveryEngine, ContentManifest, ContentAsset
from ipfs_datasets_py.multimodal_processor import MultiModalContentProcessor, ProcessedContent, ProcessedContentBatch
from ipfs_datasets_py.processors.graphrag.website_system import WebsiteGraphRAGSystem, SearchResult, WebsiteGraphRAGResult
from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import KnowledgeGraph, Entity, Relationship


class TestWebsiteGraphRAGProcessor:
    """Comprehensive test suite for WebsiteGraphRAGProcessor"""
    
    @pytest.fixture
    def mock_config(self):
        """Create mock configuration for testing"""
        return WebsiteProcessingConfig(
            archive_services=['ia'],
            crawl_depth=1,
            include_media=False,  # Disable for faster testing
            enable_graphrag=True,
            max_parallel_processing=2
        )
    
    @pytest.fixture
    def mock_processor(self, mock_config):
        """Create mock processor with test configuration"""
        return WebsiteGraphRAGProcessor(config=mock_config)
    
    @pytest.fixture
    def sample_website_data(self):
        """Sample website data for testing"""
        return {
            'url': 'https://example.com',
            'html_content': '''
                <html>
                <head><title>Test Page</title></head>
                <body>
                    <h1>AI Research Hub</h1>
                    <p>This website contains information about artificial intelligence and machine learning.</p>
                    <a href="research.pdf">Download Research Paper</a>
                    <video src="demo.mp4" controls></video>
                </body>
                </html>
            ''',
            'expected_entities': ['artificial intelligence', 'machine learning'],
            'expected_content_types': ['html', 'pdf', 'video']
        }
    
    # GIVEN WHEN THEN format tests
    
    def test_given_valid_url_when_processing_website_then_creates_graphrag_system(
        self, mock_processor, sample_website_data
    ):
        """
        GIVEN: A valid website URL with various content types
        WHEN: Processing the website into GraphRAG system
        THEN: Should create complete GraphRAG system with all discovered content
        """
        # GIVEN
        url = sample_website_data['url']
        
        # Mock the processing pipeline
        with patch.object(mock_processor, '_archive_website') as mock_archive, \
             patch.object(mock_processor, '_discover_content') as mock_discover, \
             patch.object(mock_processor, '_process_content') as mock_process, \
             patch.object(mock_processor, '_extract_knowledge_graph') as mock_kg, \
             patch.object(mock_processor, '_build_graphrag_system') as mock_build:
            
            # Setup mocks
            mock_archive.return_value = {
                'warc_files': ['/tmp/test.warc'],
                'services': {'ia': {'archived_url': 'https://web.archive.org/test'}}
            }
            
            mock_manifest = Mock(spec=ContentManifest)
            mock_manifest.base_url = url
            mock_manifest.total_assets = 3
            mock_discover.return_value = mock_manifest
            
            mock_batch = Mock(spec=ProcessedContentBatch)
            mock_batch.total_items = 3
            mock_process.return_value = mock_batch
            
            mock_graph = Mock(spec=KnowledgeGraph)
            mock_kg.return_value = mock_graph
            
            mock_graphrag = Mock()
            mock_build.return_value = mock_graphrag
            
            # WHEN
            async def _run():
                return await mock_processor.process_website(url)

            result = anyio.run(_run)
            
            # THEN
            assert result is not None
            assert isinstance(result, WebsiteGraphRAGSystem)
            assert result.url == url
            assert result.content_manifest == mock_manifest
            assert result.processed_content == mock_batch
            assert result.knowledge_graph == mock_graph
            assert result.graphrag == mock_graphrag
            
            # Verify all pipeline steps were called
            mock_archive.assert_called_once()
            mock_discover.assert_called_once()
            mock_process.assert_called_once()
            mock_kg.assert_called_once()
            mock_build.assert_called_once()
    
    def test_given_invalid_url_when_processing_then_raises_validation_error(
        self, mock_processor
    ):
        """
        GIVEN: An invalid URL format
        WHEN: Attempting to process the website
        THEN: Should raise ValueError with appropriate message
        """
        # GIVEN
        invalid_urls = [
            "not-a-url",
            "ftp://example.com",  # Unsupported protocol
            "",
            "http://",
            "https://"
        ]
        
        # WHEN/THEN
        for invalid_url in invalid_urls:
            with pytest.raises(ValueError, match="Invalid URL"):
                async def _run_invalid():
                    return await mock_processor.process_website(invalid_url)

                anyio.run(_run_invalid)
    
    def test_given_processing_error_when_processing_website_then_raises_runtime_error(
        self, mock_processor, sample_website_data
    ):
        """
        GIVEN: A valid URL but processing encounters an error
        WHEN: Processing the website
        THEN: Should raise RuntimeError with error details
        """
        # GIVEN
        url = sample_website_data['url']
        
        # Mock archive step to fail
        with patch.object(mock_processor, '_archive_website') as mock_archive:
            mock_archive.side_effect = Exception("Archive service unavailable")
            
            # WHEN/THEN
            with pytest.raises(RuntimeError, match="Processing failed"):
                async def _run_error():
                    return await mock_processor.process_website(url)

                anyio.run(_run_error)
    
    def test_given_multiple_websites_when_processing_batch_then_processes_all_successfully(
        self, mock_processor
    ):
        """
        GIVEN: Multiple website URLs
        WHEN: Processing them as a batch
        THEN: Should process all URLs and return results for successful ones
        """
        # GIVEN
        urls = [
            'https://example.com',
            'https://test.com',
            'https://demo.com'
        ]
        
        # Mock the single website processing
        with patch.object(mock_processor, 'process_website') as mock_process:
            mock_systems = [Mock(spec=WebsiteGraphRAGSystem) for _ in urls]
            mock_process.side_effect = mock_systems
            
            # WHEN
            async def _run_batch():
                return await mock_processor.process_multiple_websites(urls)

            results = anyio.run(_run_batch)
            
            # THEN
            assert len(results) == len(urls)
            assert all(isinstance(result, WebsiteGraphRAGSystem) for result in results)
            assert mock_process.call_count == len(urls)


class TestContentDiscoveryEngine:
    """Test suite for ContentDiscoveryEngine"""
    
    @pytest.fixture
    def discovery_engine(self):
        return ContentDiscoveryEngine()
    
    @pytest.fixture
    def mock_warc_content(self):
        """Mock WARC file content"""
        return {
            'html_record': {
                'rec_type': 'response',
                'target_uri': 'https://example.com/page.html',
                'content_type': 'text/html',
                'content_length': 1000,
                'payload': b'<html><body><h1>Test</h1></body></html>'
            },
            'pdf_record': {
                'rec_type': 'response',
                'target_uri': 'https://example.com/doc.pdf',
                'content_type': 'application/pdf',
                'content_length': 5000,
                'payload': b'PDF content here'
            }
        }
    
    def test_given_warc_with_mixed_content_when_discovering_then_categorizes_correctly(
        self, discovery_engine, mock_warc_content
    ):
        """
        GIVEN: A WARC file containing mixed content types (HTML, PDF, media)
        WHEN: Running content discovery
        THEN: Should correctly categorize all content types
        """
        # GIVEN
        mock_warc_path = "/tmp/test.warc"
        
        # Mock WARC parsing
        with patch.object(discovery_engine, '_parse_warc_file') as mock_parse, \
             patch('os.path.exists', return_value=True):
            mock_parse.return_value = list(mock_warc_content.values())

            # WHEN
            async def _run_discover():
                return await discovery_engine.discover_content(mock_warc_path)

            result = anyio.run(_run_discover)
            
            # THEN
            assert isinstance(result, ContentManifest)
            assert result.base_url == "https://example.com"
            assert result.total_assets >= 2
            assert len(result.html_pages) >= 1
            assert len(result.pdf_documents) >= 1
            
            # Verify content assets have correct properties
            html_page = result.html_pages[0]
            assert html_page.content_type == 'html'
            assert html_page.mime_type == 'text/html'
            assert html_page.url.endswith('.html')
            
            pdf_doc = result.pdf_documents[0] 
            assert pdf_doc.content_type == 'pdf'
            assert pdf_doc.mime_type == 'application/pdf'
            assert pdf_doc.url.endswith('.pdf')
    
    def test_given_html_with_media_when_extracting_urls_then_finds_all_media_types(
        self, discovery_engine
    ):
        """
        GIVEN: HTML content with various media elements
        WHEN: Extracting media URLs
        THEN: Should find all supported media types
        """
        # GIVEN
        html_content = '''
            <html>
            <body>
                <video src="video.mp4" width="640" height="480" controls></video>
                <audio src="audio.mp3" controls autoplay></audio>
                <img src="image.jpg" alt="Test image" width="300" height="200">
                <a href="document.pdf" title="Research Paper">Download PDF</a>
                <object data="presentation.swf" type="application/x-shockwave-flash"></object>
            </body>
            </html>
        '''
        base_url = "https://example.com"
        
        # WHEN
        async def _run_media():
            return await discovery_engine.extract_media_urls(html_content, base_url)

        media_assets = anyio.run(_run_media)
        
        # THEN
        assert len(media_assets) >= 4  # video, audio, image, pdf
        
        # Check content types are correctly identified
        content_types = [asset.content_type for asset in media_assets]
        assert 'video' in content_types
        assert 'audio' in content_types
        assert 'image' in content_types
        assert 'pdf' in content_types
        
        # Verify metadata extraction
        video_asset = next(asset for asset in media_assets if asset.content_type == 'video')
        assert video_asset.metadata['width'] == '640'
        assert video_asset.metadata['height'] == '480'
        assert video_asset.metadata['controls'] is True
        
        audio_asset = next(asset for asset in media_assets if asset.content_type == 'audio')
        assert audio_asset.metadata['controls'] is True
        assert audio_asset.metadata['autoplay'] is True
    
    def test_given_nonexistent_warc_when_discovering_then_raises_file_not_found(
        self, discovery_engine
    ):
        """
        GIVEN: A nonexistent WARC file path
        WHEN: Attempting content discovery
        THEN: Should raise FileNotFoundError
        """
        # GIVEN
        nonexistent_path = "/tmp/nonexistent.warc"
        
        # WHEN/THEN
        with pytest.raises(FileNotFoundError):
            async def _run_discover():
                return await discovery_engine.discover_content(nonexistent_path)

            anyio.run(_run_discover)


class TestMultiModalContentProcessor:
    """Test suite for MultiModalContentProcessor"""
    
    @pytest.fixture
    def content_processor(self):
        return MultiModalContentProcessor()
    
    @pytest.fixture
    def sample_content_manifest(self):
        """Create sample content manifest for testing"""
        html_asset = ContentAsset(
            url="https://example.com/page.html",
            content_type="html",
            mime_type="text/html",
            size_bytes=2000,
            content_preview='''
                <html><body>
                <h1>AI Research</h1>
                <p>This page discusses artificial intelligence and machine learning research.</p>
                </body></html>
            '''
        )
        
        pdf_asset = ContentAsset(
            url="https://example.com/paper.pdf",
            content_type="pdf", 
            mime_type="application/pdf",
            size_bytes=50000,
            metadata={'link_text': 'Research Paper', 'title': 'AI Study'}
        )
        
        return ContentManifest(
            base_url="https://example.com",
            html_pages=[html_asset],
            pdf_documents=[pdf_asset],
            media_files=[],
            structured_data=[],
            total_assets=2,
            discovery_timestamp=datetime.now()
        )
    
    def test_given_content_manifest_when_processing_batch_then_extracts_text_from_all_types(
        self, content_processor, sample_content_manifest
    ):
        """
        GIVEN: A content manifest with various content types
        WHEN: Processing the content batch
        THEN: Should extract text from all supported content types
        """
        # GIVEN
        manifest = sample_content_manifest
        
        # WHEN
        async def _run_process_batch():
            return await content_processor.process_content_batch(
                content_manifest=manifest,
                include_embeddings=False,  # Skip embeddings for speed
                include_media=False
            )

        result = anyio.run(_run_process_batch)
        
        # THEN
        assert isinstance(result, ProcessedContentBatch)
        assert result.base_url == manifest.base_url
        assert result.total_items >= 2
        
        # Check processing statistics
        assert result.processing_stats['html'] >= 1
        assert result.processing_stats['pdf'] >= 1
        assert result.processing_stats['total'] >= 2
        
        # Verify text extraction
        processed_items = result.processed_items
        html_item = next(item for item in processed_items if item.content_type == 'html')
        assert html_item.text_length > 0
        assert 'artificial intelligence' in html_item.text_content.lower()
        assert html_item.confidence_score > 0.5
        
        pdf_item = next(item for item in processed_items if item.content_type == 'pdf')
        assert pdf_item.text_length > 0
        assert pdf_item.metadata['link_text'] == 'Research Paper'
    
    def test_given_html_content_when_processing_then_extracts_clean_text_and_metadata(
        self, content_processor
    ):
        """
        GIVEN: HTML content with markup and structured data
        WHEN: Processing the HTML
        THEN: Should extract clean text and preserve metadata
        """
        # GIVEN
        html_asset = ContentAsset(
            url="https://example.com/complex.html",
            content_type="html",
            mime_type="text/html",
            size_bytes=3000,
            content_preview='''
                <html>
                <head>
                    <title>Complex Page</title>
                    <meta name="description" content="Test page description">
                </head>
                <body>
                    <h1>Main Title</h1>
                    <p>Important content about <strong>machine learning</strong>.</p>
                    <script>console.log('should be removed');</script>
                    <style>body { color: red; }</style>
                    <div class="content">More useful information here.</div>
                </body>
                </html>
            '''
        )
        
        # WHEN
        async def _run_process_html():
            return await content_processor._process_html(html_asset)

        result = anyio.run(_run_process_html)
        
        # THEN
        assert result is not None
        assert result.content_type == 'html'
        assert result.source_url == html_asset.url
        
        # Verify clean text extraction
        text = result.text_content
        assert 'Main Title' in text
        assert 'machine learning' in text
        assert 'More useful information' in text
        
        # Verify script and style content removed
        assert 'console.log' not in text
        assert 'color: red' not in text
        
        # Verify metadata extraction
        metadata = result.metadata
        assert 'original_url' in metadata
        assert 'extraction_method' in metadata
        assert metadata['mime_type'] == 'text/html'
    
    def test_given_processing_errors_when_processing_batch_then_continues_with_error_tracking(
        self, content_processor
    ):
        """
        GIVEN: Content manifest with some problematic content
        WHEN: Processing the batch
        THEN: Should continue processing and track errors appropriately
        """
        # GIVEN
        problematic_asset = ContentAsset(
            url="https://example.com/broken.html",
            content_type="html",
            mime_type="text/html",
            size_bytes=0,
            content_preview=""  # Empty content to trigger error
        )
        
        good_asset = ContentAsset(
            url="https://example.com/good.html",
            content_type="html",
            mime_type="text/html", 
            size_bytes=1000,
            content_preview="<html><body><h1>Good Content</h1></body></html>"
        )
        
        manifest = ContentManifest(
            base_url="https://example.com",
            html_pages=[problematic_asset, good_asset],
            pdf_documents=[],
            media_files=[],
            structured_data=[],
            total_assets=2,
            discovery_timestamp=datetime.now()
        )
        
        # WHEN
        async def _run_process_batch():
            return await content_processor.process_content_batch(manifest)

        result = anyio.run(_run_process_batch)
        
        # THEN
        # Should have processed the good content
        assert result.total_items >= 1
        
        # Should have at least one successful item
        successful_items = [item for item in result.processed_items if item.text_content]
        assert len(successful_items) >= 1
        
        # Verify good content was processed correctly
        good_item = next(item for item in successful_items if 'Good Content' in item.text_content)
        assert good_item is not None
        assert good_item.confidence_score > 0


class TestWebsiteGraphRAGSystem:
    """Test suite for WebsiteGraphRAGSystem"""
    
    @pytest.fixture
    def sample_graphrag_system(self):
        """Create sample GraphRAG system for testing"""
        
        # Create processed content
        html_content = ProcessedContent(
            source_url="https://example.com/ai-intro.html",
            content_type="html",
            text_content="Introduction to artificial intelligence and machine learning algorithms.",
            metadata={"title": "AI Introduction"},
            confidence_score=0.9
        )
        
        pdf_content = ProcessedContent(
            source_url="https://example.com/research.pdf",
            content_type="pdf", 
            text_content="Research paper on deep learning neural networks and their applications.",
            metadata={"title": "Deep Learning Research"},
            confidence_score=0.85
        )
        
        # Create processed batch
        processed_batch = ProcessedContentBatch(
            base_url="https://example.com",
            processed_items=[html_content, pdf_content],
            processing_stats={'html': 1, 'pdf': 1, 'total': 2}
        )
        
        # Create knowledge graph
        ai_entity = Entity(name="Artificial Intelligence", entity_type="concept")
        ml_entity = Entity(name="Machine Learning", entity_type="concept")
        dl_entity = Entity(name="Deep Learning", entity_type="concept")
        
        kg = KnowledgeGraph()
        kg.add_entity(ai_entity)
        kg.add_entity(ml_entity)
        kg.add_entity(dl_entity)
        kg.add_relationship(Relationship(ai_entity, ml_entity, "includes"))
        kg.add_relationship(Relationship(ml_entity, dl_entity, "includes"))
        
        # Create content manifest
        manifest = ContentManifest(
            base_url="https://example.com",
            html_pages=[],
            pdf_documents=[],
            media_files=[],
            structured_data=[],
            total_assets=2,
            discovery_timestamp=datetime.now()
        )
        
        return WebsiteGraphRAGSystem(
            url="https://example.com",
            content_manifest=manifest,
            processed_content=processed_batch,
            knowledge_graph=kg,
            graphrag=None  # No GraphRAG for basic testing
        )
    
    def test_given_initialized_system_when_querying_then_returns_relevant_results(
        self, sample_graphrag_system
    ):
        """
        GIVEN: A fully initialized GraphRAG system with content and knowledge graph
        WHEN: Submitting a search query
        THEN: Should return relevant results ranked by relevance
        """
        # GIVEN
        system = sample_graphrag_system
        query = "artificial intelligence machine learning"
        
        # WHEN
        async def _run_query():
            return await system.query(query, max_results=5)

        results = anyio.run(_run_query)
        
        # THEN
        assert isinstance(results, WebsiteGraphRAGResult)
        assert results.query == query
        assert results.website_url == system.url
        assert results.total_results >= 0
        
        # Should find relevant content
        if results.results:
            # Check that results contain expected content
            result_texts = [result.content_snippet for result in results.results]
            combined_text = " ".join(result_texts).lower()
            assert any(term in combined_text for term in ['artificial', 'intelligence', 'machine', 'learning'])
            
            # Verify result structure
            first_result = results.results[0]
            assert isinstance(first_result, SearchResult)
            assert first_result.source_url
            assert first_result.content_type in ['html', 'pdf']
            assert first_result.relevance_score >= 0
    
    def test_given_content_type_filter_when_querying_then_returns_only_filtered_types(
        self, sample_graphrag_system
    ):
        """
        GIVEN: A GraphRAG system with mixed content types
        WHEN: Querying with content type filter
        THEN: Should return only results from specified content types
        """
        # GIVEN
        system = sample_graphrag_system
        query = "research"
        content_types = ['pdf']  # Only PDF content
        
        # WHEN
        results = system.query(query, content_types=content_types)
        
        # THEN
        assert isinstance(results, WebsiteGraphRAGResult)
        
        # All results should be PDF type
        for result in results.results:
            assert result.content_type == 'pdf'
        
        # Verify search metadata reflects filter
        assert results.search_metadata['content_types_filter'] == content_types
    
    def test_given_specific_content_type_when_searching_by_type_then_returns_matching_content(
        self, sample_graphrag_system
    ):
        """
        GIVEN: A system with multiple content types
        WHEN: Searching within a specific content type
        THEN: Should return only content of that type
        """
        # GIVEN
        system = sample_graphrag_system
        content_type = 'html'
        
        # WHEN
        results = system.search_by_content_type(content_type)
        
        # THEN
        assert isinstance(results, list)
        
        # All results should be HTML type
        for item in results:
            assert item.content_type == content_type
        
        # Should have at least one HTML item from our test data
        assert len(results) >= 1
    
    def test_given_source_url_when_finding_related_content_then_returns_connected_content(
        self, sample_graphrag_system
    ):
        """
        GIVEN: A system with knowledge graph connections
        WHEN: Finding content related to a specific URL
        THEN: Should return content connected through knowledge graph
        """
        # GIVEN
        system = sample_graphrag_system
        source_url = "https://example.com/ai-intro.html"
        
        # WHEN
        async def _run_related_content():
            return await system.get_related_content(source_url, max_related=3)

        related_content = anyio.run(_run_related_content)
        
        # THEN
        assert isinstance(related_content, list)
        
        # Should not include the source URL itself
        related_urls = [item.source_url for item in related_content]
        assert source_url not in related_urls
        
        # Results should have similarity scores in metadata
        for item in related_content:
            if 'similarity_score' in item.metadata:
                assert 0 <= item.metadata['similarity_score'] <= 1
    
    def test_given_system_state_when_getting_overview_then_returns_comprehensive_stats(
        self, sample_graphrag_system
    ):
        """
        GIVEN: An initialized GraphRAG system
        WHEN: Getting content overview
        THEN: Should return comprehensive statistics about the system
        """
        # GIVEN
        system = sample_graphrag_system
        
        # WHEN
        overview = system.get_content_overview()
        
        # THEN
        assert isinstance(overview, dict)
        
        # Should contain key statistics
        required_keys = [
            'base_url', 'discovery_stats', 'processing_stats',
            'total_text_items', 'knowledge_graph_stats', 'graphrag_enabled'
        ]
        
        for key in required_keys:
            assert key in overview
        
        # Verify specific values
        assert overview['base_url'] == system.url
        assert overview['total_text_items'] >= 2
        assert overview['knowledge_graph_stats']['entities'] >= 3
        assert overview['knowledge_graph_stats']['relationships'] >= 2
    
    def test_given_system_with_content_when_exporting_dataset_then_creates_valid_export(
        self, sample_graphrag_system
    ):
        """
        GIVEN: A GraphRAG system with processed content
        WHEN: Exporting dataset
        THEN: Should create valid dataset file with all content
        """
        # GIVEN
        system = sample_graphrag_system
        
        # WHEN
        with tempfile.TemporaryDirectory() as temp_dir:
            # Change to temp directory for export
            import os
            original_cwd = os.getcwd()
            try:
                os.chdir(temp_dir)
                export_file = system.export_dataset(output_format="json")
                
                # THEN
                assert os.path.exists(export_file)
                assert export_file.endswith('.json')
                
                # Verify file contents
                with open(export_file, 'r', encoding='utf-8') as f:
                    dataset = json.load(f)
                
                assert 'metadata' in dataset
                assert 'content' in dataset
                assert dataset['metadata']['website_url'] == system.url
                assert len(dataset['content']) >= 2
                
                # Verify content structure
                first_item = dataset['content'][0]
                required_fields = ['source_url', 'content_type', 'text_content', 'metadata']
                for field in required_fields:
                    assert field in first_item
                    
            finally:
                os.chdir(original_cwd)


# Integration Tests
class TestWebsiteGraphRAGIntegration:
    """Integration tests for complete website processing pipeline"""
    
    @pytest.mark.integration
    @pytest.mark.slow
    def test_end_to_end_website_processing_pipeline(self):
        """
        End-to-end integration test of complete GraphRAG processing pipeline
        
        Tests the full workflow:
        1. Website archiving (mocked for reliability)
        2. Content discovery
        3. Multi-modal processing  
        4. Knowledge graph extraction
        5. GraphRAG system creation
        6. Search functionality
        """
        # GIVEN
        test_url = "https://httpbin.org/html"  # Reliable test endpoint
        
        # Create processor with minimal configuration for speed
        config = WebsiteProcessingConfig(
            archive_services=[],  # Skip external archiving for reliability
            crawl_depth=1,
            include_media=False,
            enable_graphrag=False,  # Disable GraphRAG for simpler test
            max_parallel_processing=1
        )
        
        processor = WebsiteGraphRAGProcessor(config=config)
        
        # Mock external dependencies for reliable testing
        with patch.object(processor, '_archive_website') as mock_archive, \
             patch.object(processor, '_create_local_warc') as mock_warc:
            
            # Setup archive mock
            mock_archive.return_value = {
                'warc_files': ['/tmp/test.warc'],
                'services': {},
                'timestamp': datetime.now().isoformat()
            }
            
            # Setup WARC creation mock
            mock_warc.return_value = '/tmp/test.warc'
            
            # Mock WARC file content
            with patch('os.path.exists', return_value=True):
                # WHEN - Process the website
                try:
                    async def _run_graphrag():
                        return await processor.process_website(test_url)

                    graphrag_system = anyio.run(_run_graphrag)
                    
                    # THEN - Verify system was created successfully
                    assert graphrag_system is not None
                    assert isinstance(graphrag_system, WebsiteGraphRAGSystem)
                    assert graphrag_system.url == test_url
                    
                    # Test basic system functionality
                    overview = graphrag_system.get_content_overview()
                    assert overview['base_url'] == test_url
                    
                    # Test search functionality  
                    search_results = graphrag_system.query("test content")
                    assert isinstance(search_results, WebsiteGraphRAGResult)
                    assert search_results.website_url == test_url
                    
                    print(f"Integration test successful: Processed {test_url}")
                    print(f"Content overview: {overview}")
                    print(f"Search results: {len(search_results.results)} items found")
                    
                except Exception as e:
                    pytest.fail(f"End-to-end integration test failed: {e}")
    
    @pytest.mark.integration 
    def test_error_handling_and_recovery_in_pipeline(self):
        """
        Test error handling and recovery mechanisms in the processing pipeline
        """
        # GIVEN
        test_url = "https://example.com/nonexistent"
        
        config = WebsiteProcessingConfig(
            archive_services=[],
            crawl_depth=1,
            include_media=False
        )
        
        processor = WebsiteGraphRAGProcessor(config=config)
        
        # Mock archive step to fail
        with patch.object(processor, '_archive_website') as mock_archive:
            mock_archive.side_effect = Exception("Network error")
            
            # WHEN/THEN - Should handle error gracefully
            with pytest.raises(RuntimeError, match="Processing failed"):
                async def _run_process():
                    return await processor.process_website(test_url)

                anyio.run(_run_process)


# Performance Tests
class TestPerformanceAndBenchmarks:
    """Performance benchmarks for website processing components"""
    
    @pytest.mark.benchmark
    def test_content_discovery_performance_benchmark(self, benchmark):
        """Benchmark content discovery performance"""
        
        def run_content_discovery():
            engine = ContentDiscoveryEngine()
            
            # Mock WARC with many records
            mock_records = []
            for i in range(100):  # 100 mock records
                mock_records.append({
                    'rec_type': 'response',
                    'target_uri': f'https://example.com/page{i}.html',
                    'content_type': 'text/html',
                    'content_length': 1000,
                    'payload': b'<html><body>Content</body></html>'
                })
            
            with patch.object(engine, '_parse_warc_file', return_value=mock_records):
                async def _run_engine_discover():
                    return await engine.discover_content('/tmp/test.warc')

                result = anyio.run(_run_engine_discover)
                return result
        
        result = benchmark(run_content_discovery)
        assert result.total_assets >= 100
    
    @pytest.mark.benchmark
    def test_content_processing_performance_benchmark(self, benchmark):
        """Benchmark multi-modal content processing performance"""
        
        def run_content_processing():
            processor = MultiModalContentProcessor()
            
            # Create manifest with many items
            html_assets = []
            for i in range(50):
                html_assets.append(ContentAsset(
                    url=f"https://example.com/page{i}.html",
                    content_type="html",
                    mime_type="text/html",
                    size_bytes=1000,
                    content_preview=f"<html><body><h1>Page {i}</h1><p>Content for page {i}</p></body></html>"
                ))
            
            manifest = ContentManifest(
                base_url="https://example.com",
                html_pages=html_assets,
                pdf_documents=[],
                media_files=[],
                structured_data=[],
                total_assets=len(html_assets),
                discovery_timestamp=datetime.now()
            )
            
            async def _run_process_batch():
                return await processor.process_content_batch(
                    manifest, 
                    include_embeddings=False,
                    include_media=False
                )

            result = anyio.run(_run_process_batch)
            return result
        
        result = benchmark(run_content_processing)
        assert result.total_items >= 50
    
    @pytest.mark.benchmark
    def test_graphrag_query_performance_benchmark(self, benchmark, sample_graphrag_system):
        """Benchmark GraphRAG query performance"""
        
        def run_graphrag_query():
            return sample_graphrag_system.query("artificial intelligence research")
        
        result = benchmark(run_graphrag_query)
        assert isinstance(result, WebsiteGraphRAGResult)


# Fixtures for all test classes
@pytest.fixture(scope="session")
def temp_directory():
    """Create temporary directory for test files"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


# Test configuration
def pytest_configure(config):
    """Configure pytest with custom markers"""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
    config.addinivalue_line(
        "markers", "benchmark: mark test as performance benchmark"
    )


# Example usage for running tests
if __name__ == "__main__":
    # Run specific test
    pytest.main([
        __file__ + "::TestWebsiteGraphRAGProcessor::test_given_valid_url_when_processing_website_then_creates_graphrag_system",
        "-v"
    ])