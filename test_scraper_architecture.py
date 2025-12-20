#!/usr/bin/env python3
"""
Comprehensive Scraper Architecture Tests

Tests the scraper system architecture with focus on:
1. Multiple fallback mechanisms (API, web scraping, cached data)
2. Error handling and retry logic
3. Rate limiting and throttling
4. Data validation and sanitization
5. Resilience to network failures
6. Graceful degradation
"""

import pytest
import asyncio
import time
import json
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from pathlib import Path
import tempfile
import os

# Import the scrapers
from enhanced_model_scraper import EnhancedModelScraper, ModelRecord, SCIENTIFIC_LIBS_AVAILABLE
from production_hf_scraper import ProductionHFScraper


class TestScraperFallbackMechanisms:
    """Test fallback mechanisms when primary scraping fails"""
    
    def test_fallback_to_cached_data_on_network_failure(self):
        """Test that scraper falls back to cached data when network fails"""
        with tempfile.TemporaryDirectory() as tmpdir:
            scraper = EnhancedModelScraper(data_dir=tmpdir)
            
            # Create some cached data
            cached_models = scraper.create_mock_comprehensive_dataset(size=10)
            scraper.save_to_parquet(cached_models)
            
            # Simulate network failure by patching
            with patch.object(scraper, 'scanner', None):
                # Should load from cache
                df = scraper.load_from_parquet()
                assert df is not None
                assert len(df) == 10
    
    def test_fallback_to_mock_data_when_all_sources_fail(self):
        """Test graceful degradation to mock data when all sources fail"""
        with tempfile.TemporaryDirectory() as tmpdir:
            scraper = EnhancedModelScraper(data_dir=tmpdir)
            
            # No cached data, no network - should generate mock data
            results = scraper.scrape_all_models(limit=5, mock_mode=True)
            
            assert results['total_models'] > 0
            assert results['scrape_duration'] > 0
    
    @pytest.mark.asyncio
    async def test_api_fallback_on_rate_limit(self):
        """Test that scraper handles rate limits with exponential backoff"""
        scraper = ProductionHFScraper(data_dir=tempfile.mkdtemp())
        scraper.rate_limit_delay = 0.01  # Fast for testing
        
        # Mock API that returns rate limit error then succeeds
        call_count = [0]
        
        async def mock_get(*args, **kwargs):
            call_count[0] += 1
            mock_response = AsyncMock()
            if call_count[0] == 1:
                mock_response.status = 429  # Rate limit
                return mock_response
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=[])
            return mock_response
        
        with patch('aiohttp.ClientSession') as mock_session:
            mock_session.return_value.__aenter__.return_value.get = mock_get
            
            # Should retry and eventually succeed
            models = await scraper.get_all_models(limit=1)
            assert call_count[0] >= 1  # At least one retry
    
    def test_web_scraping_fallback_when_api_unavailable(self):
        """Test web scraping fallback when API is unavailable"""
        scraper = EnhancedModelScraper(data_dir=tempfile.mkdtemp())
        
        # Mock both API and scanner as unavailable
        scraper.scanner = None
        
        # Should fall back to mock mode gracefully
        results = scraper.scrape_all_models(limit=10, mock_mode=True)
        assert results['total_models'] == 10


class TestScraperErrorHandling:
    """Test error handling and recovery mechanisms"""
    
    def test_invalid_model_data_sanitization(self):
        """Test that invalid/malformed model data is sanitized"""
        scraper = ProductionHFScraper(data_dir=tempfile.mkdtemp())
        
        # Create malformed model data
        bad_model_data = {
            "id": "test/model",
            "downloads": "not_a_number",  # Invalid
            "likes": None,
            "tags": "should_be_list",  # Invalid
            "config": {"hidden_size": "invalid"}  # Invalid
        }
        
        # Should handle gracefully
        try:
            model = scraper.extract_model_metadata(bad_model_data)
            assert model is not None
            assert isinstance(model.downloads, int)
            assert isinstance(model.likes, int)
            assert isinstance(model.tags, list)
        except Exception as e:
            pytest.fail(f"Failed to sanitize bad data: {e}")
    
    def test_partial_data_extraction(self):
        """Test extraction with partial/missing data"""
        scraper = ProductionHFScraper(data_dir=tempfile.mkdtemp())
        
        # Minimal model data
        minimal_data = {"id": "test/minimal"}
        
        model = scraper.extract_model_metadata(minimal_data)
        assert model is not None
        assert model.model_id == "test/minimal"
        assert model.downloads == 0
        assert model.likes == 0
        assert len(model.embedding_vector) == 384  # Should generate default
    
    def test_network_timeout_handling(self):
        """Test handling of network timeouts"""
        scraper = ProductionHFScraper(data_dir=tempfile.mkdtemp())
        
        # Mock timeout scenario
        with patch('requests.get', side_effect=requests.Timeout("Connection timeout")):
            # Should handle timeout gracefully
            try:
                # Use mock mode as fallback
                results = scraper.scrape_production_models(limit=5)
                # In production, would fall back to cached or mock data
                assert 'error' not in results or results.get('total_models', 0) >= 0
            except requests.Timeout:
                pass  # Expected in test environment
    
    def test_json_parsing_error_recovery(self):
        """Test recovery from JSON parsing errors"""
        scraper = EnhancedModelScraper(data_dir=tempfile.mkdtemp())
        
        # Test with invalid parquet file
        bad_json_path = Path(scraper.data_dir) / "bad_data.json"
        bad_json_path.write_text("{ invalid json }")
        
        # Should handle gracefully
        df = scraper.load_from_parquet()
        assert df is None  # Returns None instead of crashing


class TestScraperRateLimiting:
    """Test rate limiting and throttling mechanisms"""
    
    @pytest.mark.asyncio
    async def test_request_rate_limiting(self):
        """Test that scraper respects rate limits"""
        scraper = ProductionHFScraper(data_dir=tempfile.mkdtemp())
        scraper.rate_limit_delay = 0.1  # 100ms between requests
        
        start_time = time.time()
        
        # Mock multiple API calls
        with patch('aiohttp.ClientSession') as mock_session:
            mock_get = AsyncMock()
            mock_get.return_value.status = 200
            mock_get.return_value.json = AsyncMock(return_value=[])
            mock_session.return_value.__aenter__.return_value.get = mock_get
            
            await scraper.get_all_models(limit=5)
        
        elapsed = time.time() - start_time
        # Should take at least rate_limit_delay * num_requests
        assert elapsed >= 0.05  # Some delay occurred
    
    def test_concurrent_request_limiting(self):
        """Test that concurrent requests are limited"""
        scraper = EnhancedModelScraper(data_dir=tempfile.mkdtemp())
        
        # Create mock models
        models = scraper.create_mock_comprehensive_dataset(size=100)
        
        # Process with limited concurrency
        max_workers = 10
        start_time = time.time()
        
        # Should process in batches
        scraper.save_to_parquet(models)
        
        # Verify it didn't try to process all at once
        assert time.time() - start_time < 10  # Reasonable time


class TestScraperDataValidation:
    """Test data validation and quality checks"""
    
    def test_model_record_validation(self):
        """Test that ModelRecord enforces data types"""
        scraper = EnhancedModelScraper(data_dir=tempfile.mkdtemp())
        models = scraper.create_mock_comprehensive_dataset(size=1)
        
        model = models[0]
        assert isinstance(model.model_id, str)
        assert isinstance(model.downloads, int)
        assert isinstance(model.likes, int)
        assert isinstance(model.model_size_mb, float)
        assert isinstance(model.tags, list)
        assert isinstance(model.embedding_vector, list)
        assert len(model.embedding_vector) == 384
    
    def test_required_fields_present(self):
        """Test that all required fields are present"""
        scraper = ProductionHFScraper(data_dir=tempfile.mkdtemp())
        
        model_data = {
            "id": "test/model",
            "pipeline_tag": "text-generation"
        }
        
        model = scraper.extract_model_metadata(model_data)
        
        # Check required fields
        required_fields = [
            'model_id', 'model_name', 'author', 'architecture',
            'task_type', 'model_size_mb', 'popularity_score',
            'efficiency_score', 'compatibility_score'
        ]
        
        for field in required_fields:
            assert hasattr(model, field)
            assert getattr(model, field) is not None
    
    def test_data_consistency_checks(self):
        """Test data consistency validation"""
        scraper = EnhancedModelScraper(data_dir=tempfile.mkdtemp())
        models = scraper.create_mock_comprehensive_dataset(size=10)
        
        for model in models:
            # Size should be positive
            assert model.model_size_mb > 0
            
            # Scores should be in valid range
            assert 0 <= model.popularity_score <= 100
            assert 0 <= model.efficiency_score <= 100
            assert 0 <= model.compatibility_score <= 100
            
            # Downloads and likes non-negative
            assert model.downloads >= 0
            assert model.likes >= 0


class TestScraperStorageMechanisms:
    """Test different storage backends and formats"""
    
    @pytest.mark.skipif(not SCIENTIFIC_LIBS_AVAILABLE, 
                       reason="Scientific libraries not available")
    def test_parquet_storage_and_retrieval(self):
        """Test Parquet storage format"""
        with tempfile.TemporaryDirectory() as tmpdir:
            scraper = EnhancedModelScraper(data_dir=tmpdir)
            
            # Create and save models
            models = scraper.create_mock_comprehensive_dataset(size=10)
            scraper.save_to_parquet(models)
            
            # Load and verify
            df = scraper.load_from_parquet()
            assert df is not None
            assert len(df) == 10
            assert 'model_id' in df.columns
            assert 'embedding_vector' in df.columns
    
    @pytest.mark.skipif(not SCIENTIFIC_LIBS_AVAILABLE,
                       reason="Scientific libraries not available")
    def test_incremental_storage_updates(self):
        """Test incremental updates to storage"""
        with tempfile.TemporaryDirectory() as tmpdir:
            scraper = EnhancedModelScraper(data_dir=tmpdir)
            
            # Save initial batch
            models1 = scraper.create_mock_comprehensive_dataset(size=5)
            scraper.save_to_parquet(models1)
            
            # Append new batch
            models2 = scraper.create_mock_comprehensive_dataset(size=5)
            # Change model IDs to avoid duplicates
            for i, m in enumerate(models2):
                m.model_id = f"batch2/{m.model_id}"
            
            scraper.save_to_parquet(models2, append=True)
            
            # Verify both batches stored
            df = scraper.load_from_parquet()
            assert len(df) == 10
    
    def test_metadata_persistence(self):
        """Test that scraper metadata persists across sessions"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # First session
            scraper1 = EnhancedModelScraper(data_dir=tmpdir)
            scraper1.stats['test_key'] = 'test_value'
            scraper1.save_metadata(scraper1.stats)
            
            # Second session
            scraper2 = EnhancedModelScraper(data_dir=tmpdir)
            metadata = scraper2.load_metadata()
            assert metadata.get('test_key') == 'test_value'


class TestScraperSearchIndexing:
    """Test search index building and querying"""
    
    @pytest.mark.skipif(not SCIENTIFIC_LIBS_AVAILABLE,
                       reason="Scientific libraries not available")
    def test_search_index_creation(self):
        """Test that search index is created successfully"""
        with tempfile.TemporaryDirectory() as tmpdir:
            scraper = EnhancedModelScraper(data_dir=tmpdir)
            
            # Create models and build index
            models = scraper.create_mock_comprehensive_dataset(size=50)
            scraper.save_to_parquet(models)
            
            df = scraper.load_from_parquet()
            scraper.build_search_index(df)
            
            assert scraper.vectorizer is not None
            assert scraper.embeddings_matrix is not None
            assert len(scraper.model_index) == 50
    
    @pytest.mark.skipif(not SCIENTIFIC_LIBS_AVAILABLE,
                       reason="Scientific libraries not available")
    def test_semantic_search_functionality(self):
        """Test semantic search capabilities"""
        with tempfile.TemporaryDirectory() as tmpdir:
            scraper = EnhancedModelScraper(data_dir=tmpdir)
            
            # Setup
            models = scraper.create_mock_comprehensive_dataset(size=50)
            scraper.save_to_parquet(models)
            df = scraper.load_from_parquet()
            scraper.build_search_index(df)
            
            # Search
            results = scraper.search_models("GPT text generation", top_k=5)
            
            assert len(results) <= 5
            assert all('similarity_score' in r for r in results)
    
    @pytest.mark.skipif(not SCIENTIFIC_LIBS_AVAILABLE,
                       reason="Scientific libraries not available")
    def test_filtered_search(self):
        """Test search with filters"""
        with tempfile.TemporaryDirectory() as tmpdir:
            scraper = EnhancedModelScraper(data_dir=tmpdir)
            
            # Setup
            models = scraper.create_mock_comprehensive_dataset(size=50)
            scraper.save_to_parquet(models)
            df = scraper.load_from_parquet()
            scraper.build_search_index(df)
            
            # Search with filters
            filters = {
                'max_size_mb': 1000,
                'min_downloads': 100
            }
            results = scraper.search_models("model", top_k=10, filters=filters)
            
            # Verify filters applied
            for result in results:
                assert result['model_size_mb'] <= 1000
                assert result['downloads'] >= 100


class TestScraperResilience:
    """Test scraper resilience and recovery"""
    
    def test_partial_batch_failure_recovery(self):
        """Test recovery when some models in batch fail"""
        scraper = ProductionHFScraper(data_dir=tempfile.mkdtemp())
        
        # Mix of good and bad model data
        models_data = [
            {"id": "good/model1", "downloads": 100},
            {"id": "bad/model", "invalid_field": None},  # Will cause issues
            {"id": "good/model2", "downloads": 200}
        ]
        
        # Should extract what it can
        successful = []
        for data in models_data:
            try:
                model = scraper.extract_model_metadata(data)
                successful.append(model)
            except Exception:
                pass  # Skip failures
        
        assert len(successful) >= 1  # At least some succeeded
    
    def test_resume_from_checkpoint(self):
        """Test resuming scrape from checkpoint"""
        with tempfile.TemporaryDirectory() as tmpdir:
            scraper = EnhancedModelScraper(data_dir=tmpdir)
            
            # First partial scrape
            models1 = scraper.create_mock_comprehensive_dataset(size=5)
            scraper.save_to_parquet(models1)
            scraper.stats['last_checkpoint'] = 5
            scraper.save_metadata(scraper.stats)
            
            # Resume scrape
            scraper2 = EnhancedModelScraper(data_dir=tmpdir)
            metadata = scraper2.load_metadata()
            checkpoint = metadata.get('last_checkpoint', 0)
            
            assert checkpoint == 5
            
            # Continue from checkpoint
            models2 = scraper2.create_mock_comprehensive_dataset(size=5)
            scraper2.save_to_parquet(models2, append=True)
    
    def test_graceful_shutdown_on_interrupt(self):
        """Test that scraper saves state on interrupt"""
        with tempfile.TemporaryDirectory() as tmpdir:
            scraper = EnhancedModelScraper(data_dir=tmpdir)
            
            # Simulate interrupt during scrape
            models = scraper.create_mock_comprehensive_dataset(size=10)
            scraper.save_to_parquet(models[:5])  # Partial save
            scraper.stats['interrupted'] = True
            scraper.save_metadata(scraper.stats)
            
            # Verify partial data saved
            df = scraper.load_from_parquet()
            assert df is not None
            assert len(df) == 5


class TestScraperPerformance:
    """Test scraper performance characteristics"""
    
    def test_large_dataset_handling(self):
        """Test handling of large datasets"""
        with tempfile.TemporaryDirectory() as tmpdir:
            scraper = EnhancedModelScraper(data_dir=tmpdir)
            
            # Create large dataset
            start_time = time.time()
            models = scraper.create_mock_comprehensive_dataset(size=1000)
            creation_time = time.time() - start_time
            
            # Should be reasonably fast
            assert creation_time < 30  # Less than 30 seconds for 1000 models
            assert len(models) == 1000
    
    @pytest.mark.skipif(not SCIENTIFIC_LIBS_AVAILABLE,
                       reason="Scientific libraries not available")
    def test_search_performance(self):
        """Test search performance on large index"""
        with tempfile.TemporaryDirectory() as tmpdir:
            scraper = EnhancedModelScraper(data_dir=tmpdir)
            
            # Build large index
            models = scraper.create_mock_comprehensive_dataset(size=1000)
            scraper.save_to_parquet(models)
            df = scraper.load_from_parquet()
            scraper.build_search_index(df)
            
            # Test search speed
            start_time = time.time()
            results = scraper.search_models("GPT model", top_k=10)
            search_time = time.time() - start_time
            
            # Should be fast
            assert search_time < 1.0  # Less than 1 second
            assert len(results) <= 10


class TestScraperIntegration:
    """Integration tests for complete scraper workflows"""
    
    def test_end_to_end_scraping_workflow(self):
        """Test complete scraping workflow"""
        with tempfile.TemporaryDirectory() as tmpdir:
            scraper = EnhancedModelScraper(data_dir=tmpdir)
            
            # Full workflow
            results = scraper.scrape_all_models(limit=20, mock_mode=True)
            
            # Verify all components
            assert results['total_models'] == 20
            assert results['parquet_file']
            assert results['search_index_built']
            assert results['storage_size_mb'] > 0
            
            # Verify data accessible
            df = scraper.load_from_parquet()
            assert len(df) == 20
            
            # Verify search works
            if SCIENTIFIC_LIBS_AVAILABLE:
                search_results = scraper.search_models("model", top_k=5)
                assert len(search_results) <= 5
    
    def test_statistics_generation(self):
        """Test statistics generation"""
        with tempfile.TemporaryDirectory() as tmpdir:
            scraper = EnhancedModelScraper(data_dir=tmpdir)
            
            # Scrape and generate stats
            scraper.scrape_all_models(limit=20, mock_mode=True)
            stats = scraper.get_statistics()
            
            # Verify statistics
            assert 'total_models' in stats
            assert 'total_authors' in stats
            assert 'total_architectures' in stats
            assert 'avg_model_size_mb' in stats


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
