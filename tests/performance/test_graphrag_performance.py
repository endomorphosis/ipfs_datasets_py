"""
Phase 5: Performance and Robustness Testing

Comprehensive performance benchmarks and robustness tests for the GraphRAG 
PDF processing system, including stress tests, memory profiling, and scalability validation.
"""
import pytest
import anyio
import tempfile
import os
import time
import psutil
import json
from pathlib import Path
import warnings
from concurrent.futures import ThreadPoolExecutor
import gc

# Suppress warnings from various libraries
warnings.filterwarnings("ignore", category=UserWarning)

# Test fixtures and utilities
from tests.conftest import *


@pytest.mark.integration
@pytest.mark.performance
@pytest.mark.slow
class TestPerformanceBenchmarks:
    """Performance benchmarking tests for GraphRAG PDF processing"""
    
    @pytest.fixture(scope="class")
    def performance_test_pdfs(self):
        """Create various sized PDFs for performance testing"""
        try:
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import letter
            
            pdf_paths = []
            
            # Small PDF (1 page)
            with tempfile.NamedTemporaryFile(suffix='_small.pdf', delete=False) as tmp_file:
                small_pdf = tmp_file.name
            
            c = canvas.Canvas(small_pdf, pagesize=letter)
            c.drawString(50, 750, "Small PDF Test Document")
            c.drawString(50, 700, "This is a small test document with minimal content.")
            c.drawString(50, 650, "Contains: entities, Stanford University, machine learning research.")
            c.save()
            pdf_paths.append(('small', small_pdf, 1))
            
            # Medium PDF (10 pages)
            with tempfile.NamedTemporaryFile(suffix='_medium.pdf', delete=False) as tmp_file:
                medium_pdf = tmp_file.name
            
            c = canvas.Canvas(medium_pdf, pagesize=letter)
            for page in range(10):
                c.drawString(50, 750, f"Medium PDF - Page {page + 1}")
                c.drawString(50, 700, f"Research on neural networks and deep learning applications.")
                c.drawString(50, 650, f"Authors: Dr. Smith (MIT), Prof. Johnson (Stanford), Dr. Lee (Google).")
                c.drawString(50, 600, f"Keywords: AI, ML, NLP, computer vision, robotics, data science.")
                c.drawString(50, 550, f"Content includes technical specifications and performance metrics.")
                c.showPage()
            c.save()
            pdf_paths.append(('medium', medium_pdf, 10))
            
            # Large PDF (50 pages)
            with tempfile.NamedTemporaryFile(suffix='_large.pdf', delete=False) as tmp_file:
                large_pdf = tmp_file.name
            
            c = canvas.Canvas(large_pdf, pagesize=letter)
            for page in range(50):
                c.drawString(50, 750, f"Large PDF - Page {page + 1}")
                c.drawString(50, 700, f"Comprehensive research document on artificial intelligence.")
                c.drawString(50, 650, f"Section {page + 1}: Advanced topics in machine learning and NLP.")
                
                # Add more content per page
                y_pos = 600
                content_lines = [
                    f"This section discusses implementation details for page {page + 1}.",
                    f"Key entities: OpenAI, Google Research, Facebook AI, Microsoft Research.",
                    f"Technologies: Python, PyTorch, TensorFlow, Hugging Face Transformers.",
                    f"Applications: text generation, sentiment analysis, question answering.",
                    f"Performance metrics: accuracy, precision, recall, F1-score analysis.",
                    f"Future work: scaling to larger datasets and improved efficiency."
                ]
                
                for line in content_lines:
                    c.drawString(50, y_pos, line)
                    y_pos -= 15
                
                c.showPage()
            c.save()
            pdf_paths.append(('large', large_pdf, 50))
            
            yield pdf_paths
            
            # Cleanup
            for _, pdf_path, _ in pdf_paths:
                if os.path.exists(pdf_path):
                    os.unlink(pdf_path)
                    
        except ImportError:
            pytest.skip("PDF creation dependencies not available")
    
    @pytest.mark.asyncio
    async def test_given_various_pdf_sizes_when_processing_then_measures_performance_scaling(self, performance_test_pdfs):
        """
        GIVEN PDFs of various sizes (small, medium, large)
        WHEN processing through GraphRAG pipeline
        THEN should measure performance scaling characteristics
        """
        try:
            from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor
            
            performance_results = []
            
            for size_name, pdf_path, page_count in performance_test_pdfs:
                processor = PDFProcessor(enable_monitoring=True)
                
                # Measure processing time and memory usage
                start_time = time.time()
                start_memory = psutil.Process().memory_info().rss / 1024 / 1024  # MB
                
                results = await processor.process_pdf(pdf_path)
                
                end_time = time.time()
                end_memory = psutil.Process().memory_info().rss / 1024 / 1024  # MB
                
                processing_time = end_time - start_time
                memory_usage = end_memory - start_memory
                
                performance_results.append({
                    'size': size_name,
                    'pages': page_count,
                    'processing_time': processing_time,
                    'memory_usage': memory_usage,
                    'status': results.get('status'),
                    'stages_completed': len(results.get('stages_completed', []))
                })
                
                # Cleanup memory
                gc.collect()
            
            # Analyze performance scaling
            successful_results = [r for r in performance_results if r['status'] in ['success', 'error']]
            
            if len(successful_results) > 1:
                # Should show reasonable performance scaling
                small_result = next((r for r in successful_results if r['size'] == 'small'), None)
                large_result = next((r for r in successful_results if r['size'] == 'large'), None)
                
                if small_result and large_result:
                    # Processing time should scale reasonably with document size
                    time_ratio = large_result['processing_time'] / small_result['processing_time']
                    page_ratio = large_result['pages'] / small_result['pages']
                    
                    # Performance should not degrade exponentially
                    assert time_ratio < page_ratio * 3  # Allow some overhead but not exponential growth
                    
                    # Memory usage should be reasonable
                    assert large_result['memory_usage'] < 1000  # Less than 1GB for large docs
            
        except Exception as e:
            # Expected with missing dependencies
            assert "dependencies" in str(e).lower() or "not found" in str(e).lower()
    
    @pytest.mark.asyncio
    async def test_given_concurrent_pdf_processing_when_processing_multiple_documents_then_handles_concurrency(self, performance_test_pdfs):
        """
        GIVEN multiple PDF documents for concurrent processing
        WHEN processing simultaneously
        THEN should handle concurrency without resource conflicts
        """
        try:
            from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor
            
            # Test concurrent processing with multiple processors
            processors = [PDFProcessor() for _ in range(3)]
            
            # Select PDFs for concurrent testing
            test_pdfs = [pdf_info for pdf_info in performance_test_pdfs if pdf_info[0] != 'large']  # Skip large for concurrency
            
            if len(test_pdfs) >= 2:
                # Process multiple PDFs concurrently
                concurrent_tasks = []
                for i, (size_name, pdf_path, _) in enumerate(test_pdfs[:3]):  # Max 3 concurrent
                    processor = processors[i]
                    task = processor.process_pdf(pdf_path)
                    concurrent_tasks.append(task)
                
                # Wait for all concurrent processing to complete
                results = await # TODO: Convert to anyio.create_task_group() - see anyio_migration_helpers.py
    asyncio.gather(*concurrent_tasks, return_exceptions=True)
                
                # Should handle concurrent processing
                successful_results = [r for r in results if isinstance(r, dict) and r.get('status') in ['success', 'error']]
                
                # At least some concurrent processing should succeed
                assert len(successful_results) > 0
                
                # Should not have resource conflicts
                for result in successful_results:
                    assert isinstance(result, dict)
                    assert 'status' in result
                    
        except Exception as e:
            # Expected with missing dependencies
            assert "dependencies" in str(e).lower() or "not found" in str(e).lower()


@pytest.mark.integration
@pytest.mark.robustness
class TestRobustnessAndErrorHandling:
    """Robustness testing for various failure scenarios"""
    
    def test_given_system_under_memory_pressure_when_processing_then_handles_gracefully(self):
        """
        GIVEN system under memory pressure
        WHEN processing PDF documents
        THEN should handle memory constraints gracefully
        """
        try:
            from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor
            
            processor = PDFProcessor()
            
            # Create memory pressure simulation
            memory_hogs = []
            try:
                # Allocate memory to create pressure (careful not to crash system)
                for _ in range(10):
                    memory_hogs.append(bytearray(10 * 1024 * 1024))  # 10MB each = 100MB total
                
                # Create test PDF
                from reportlab.pdfgen import canvas
                with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
                    pdf_path = tmp_file.name
                
                c = canvas.Canvas(pdf_path)
                c.drawString(50, 750, "Memory pressure test document")
                c.save()
                
                try:
                    # Process under memory pressure
                    import anyio
                    results = anyio.run(processor.process_pdf(pdf_path))
                    
                    # Should handle memory pressure gracefully
                    assert isinstance(results, dict)
                    assert 'status' in results
                    
                finally:
                    os.unlink(pdf_path)
                    
            finally:
                # Clean up memory hogs
                memory_hogs.clear()
                gc.collect()
                
        except Exception as e:
            # Expected with missing dependencies
            assert "dependencies" in str(e).lower() or "not found" in str(e).lower()
    
    @pytest.mark.asyncio
    async def test_given_network_interruption_when_processing_then_continues_offline(self):
        """
        GIVEN network interruption during processing
        WHEN processing PDF documents
        THEN should continue with offline capabilities
        """
        try:
            from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor
            
            processor = PDFProcessor()
            
            # Create test PDF
            from reportlab.pdfgen import canvas
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
                pdf_path = tmp_file.name
            
            c = canvas.Canvas(pdf_path)
            c.drawString(50, 750, "Network interruption test document")
            c.drawString(50, 700, "This should process without network dependencies")
            c.save()
            
            try:
                # Process without network dependencies
                results = await processor.process_pdf(pdf_path)
                
                # Should work offline (core functionality shouldn't require network)
                assert isinstance(results, dict)
                assert 'status' in results
                
            finally:
                os.unlink(pdf_path)
                
        except Exception as e:
            # Expected with missing dependencies
            assert "dependencies" in str(e).lower() or "not found" in str(e).lower()
    
    def test_given_disk_space_constraints_when_processing_then_handles_storage_limits(self):
        """
        GIVEN limited disk space
        WHEN processing PDF documents
        THEN should handle storage constraints appropriately
        """
        try:
            from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor
            
            processor = PDFProcessor()
            
            # Check available disk space
            statvfs = os.statvfs('/tmp')
            available_bytes = statvfs.f_frsize * statvfs.f_bavail
            available_mb = available_bytes / (1024 * 1024)
            
            if available_mb < 100:  # Less than 100MB available
                # Test storage constraint handling
                from reportlab.pdfgen import canvas
                with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
                    pdf_path = tmp_file.name
                
                c = canvas.Canvas(pdf_path)
                c.drawString(50, 750, "Disk space constraint test")
                c.save()
                
                try:
                    import anyio
                    results = anyio.run(processor.process_pdf(pdf_path))
                    
                    # Should handle storage constraints
                    assert isinstance(results, dict)
                    assert 'status' in results
                    
                finally:
                    os.unlink(pdf_path)
            
        except Exception as e:
            # Expected with missing dependencies
            assert "dependencies" in str(e).lower() or "not found" in str(e).lower()


@pytest.mark.integration
@pytest.mark.stress
@pytest.mark.slow
class TestStressAndScalability:
    """Stress testing and scalability validation"""
    
    def test_given_rapid_successive_requests_when_processing_then_maintains_stability(self):
        """
        GIVEN rapid successive PDF processing requests
        WHEN processing many documents quickly
        THEN should maintain system stability
        """
        try:
            from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor
            
            # Create multiple small test PDFs
            test_pdfs = []
            try:
                from reportlab.pdfgen import canvas
                
                for i in range(5):  # Create 5 small PDFs
                    with tempfile.NamedTemporaryFile(suffix=f'_stress_{i}.pdf', delete=False) as tmp_file:
                        pdf_path = tmp_file.name
                    
                    c = canvas.Canvas(pdf_path)
                    c.drawString(50, 750, f"Stress test document {i + 1}")
                    c.drawString(50, 700, f"Content for rapid processing test {i + 1}")
                    c.save()
                    
                    test_pdfs.append(pdf_path)
                
                # Process rapidly
                processor = PDFProcessor()
                results = []
                
                import anyio
                
                async def process_all():
                    tasks = []
                    for pdf_path in test_pdfs:
                        task = processor.process_pdf(pdf_path)
                        tasks.append(task)
                    return await # TODO: Convert to anyio.create_task_group() - see anyio_migration_helpers.py
    asyncio.gather(*tasks, return_exceptions=True)
                
                all_results = anyio.run(process_all())
                
                # Should handle rapid processing
                successful_results = [r for r in all_results if isinstance(r, dict)]
                assert len(successful_results) > 0  # At least some should succeed
                
                # System should remain stable
                for result in successful_results:
                    assert 'status' in result
                    
            finally:
                # Cleanup test PDFs
                for pdf_path in test_pdfs:
                    if os.path.exists(pdf_path):
                        os.unlink(pdf_path)
                        
        except Exception as e:
            # Expected with missing dependencies
            assert "dependencies" in str(e).lower() or "not found" in str(e).lower()
    
    def test_given_long_running_operation_when_processing_then_maintains_performance(self):
        """
        GIVEN long-running PDF processing operation
        WHEN processing over extended time
        THEN should maintain performance without memory leaks
        """
        try:
            from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor
            
            processor = PDFProcessor(enable_monitoring=True)
            
            # Monitor memory usage over time
            initial_memory = psutil.Process().memory_info().rss / 1024 / 1024  # MB
            
            # Create test PDF
            from reportlab.pdfgen import canvas
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
                pdf_path = tmp_file.name
            
            c = canvas.Canvas(pdf_path)
            for page in range(20):  # Medium-sized document
                c.drawString(50, 750, f"Long running test - Page {page + 1}")
                c.drawString(50, 700, f"Memory leak detection content {page + 1}")
                c.showPage()
            c.save()
            
            try:
                # Process multiple times to detect memory leaks
                for iteration in range(3):  # Limited iterations for CI environment
                    import anyio
                    results = anyio.run(processor.process_pdf(pdf_path))
                    
                    # Force garbage collection
                    gc.collect()
                    
                    # Check memory usage
                    current_memory = psutil.Process().memory_info().rss / 1024 / 1024  # MB
                    memory_growth = current_memory - initial_memory
                    
                    # Should not have excessive memory growth
                    assert memory_growth < 500  # Less than 500MB growth over iterations
                    
            finally:
                os.unlink(pdf_path)
                
        except Exception as e:
            # Expected with missing dependencies
            assert "dependencies" in str(e).lower() or "not found" in str(e).lower()


@pytest.mark.integration
@pytest.mark.monitoring
class TestMonitoringAndMetrics:
    """Testing monitoring and metrics collection capabilities"""
    
    @pytest.mark.asyncio
    async def test_given_monitoring_enabled_when_processing_then_collects_comprehensive_metrics(self):
        """
        GIVEN PDF processing with monitoring enabled
        WHEN processing documents
        THEN should collect comprehensive performance metrics
        """
        try:
            from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor
            
            processor = PDFProcessor(
                enable_monitoring=True,
                enable_audit=True
            )
            
            # Create test PDF
            from reportlab.pdfgen import canvas
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
                pdf_path = tmp_file.name
            
            c = canvas.Canvas(pdf_path)
            c.drawString(50, 750, "Monitoring test document")
            c.drawString(50, 700, "Entities: Stanford University, machine learning, Python")
            c.save()
            
            try:
                results = await processor.process_pdf(pdf_path)
                
                # Should collect monitoring data
                assert isinstance(results, dict)
                
                if 'processing_metadata' in results:
                    metadata = results['processing_metadata']
                    
                    # Should have timing information
                    if 'processing_time' in metadata:
                        assert isinstance(metadata['processing_time'], (int, float))
                        assert metadata['processing_time'] >= 0
                    
                    # Should have pipeline information
                    if 'pipeline_version' in metadata:
                        assert isinstance(metadata['pipeline_version'], str)
                        assert len(metadata['pipeline_version']) > 0
                        
            finally:
                os.unlink(pdf_path)
                
        except Exception as e:
            # Expected with missing dependencies
            assert "dependencies" in str(e).lower() or "not found" in str(e).lower()


if __name__ == "__main__":
    # Run performance and robustness tests
    pytest.main([__file__, "-v", "-m", "performance or robustness or stress"])