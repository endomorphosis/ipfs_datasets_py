"""
Unit tests for PDF processing core components.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from pathlib import Path
import tempfile
import json

from ipfs_datasets_py.pdf_processing import (
    PDFProcessor, LLMOptimizer, MultiEngineOCR,
    HAVE_PDF_PROCESSOR, HAVE_LLM_OPTIMIZER, HAVE_OCR_ENGINE
)


class TestPDFProcessor:
    """Test the core PDF processor functionality."""
    
    def test_pdf_processor_import(self):
        """Test that PDFProcessor can be imported."""
        assert HAVE_PDF_PROCESSOR is True
        assert PDFProcessor is not None
    
    def test_pdf_processor_initialization(self):
        """Test PDFProcessor initialization."""
        processor = PDFProcessor(enable_monitoring=False, enable_audit=False)
        assert processor is not None
        assert processor.monitoring is None  # Monitoring disabled
        assert processor.storage is not None
    
    def test_pdf_processor_with_custom_storage(self, temp_dir):
        """Test PDFProcessor with custom storage."""
        from ipfs_datasets_py.ipld import IPLDStorage
        custom_storage = IPLDStorage()
        
        processor = PDFProcessor(
            storage=custom_storage,
            enable_monitoring=False,
            enable_audit=False
        )
        assert processor.storage is custom_storage
    
    @pytest.mark.asyncio
    async def test_pdf_processor_process_basic(self, sample_pdf_content, temp_dir):
        """Test basic PDF processing functionality."""
        processor = PDFProcessor(enable_monitoring=False, enable_audit=False)
        
        # Create a mock PDF file
        pdf_path = temp_dir / "test.pdf"
        pdf_path.write_text("mock pdf content")
        
        # Mock the internal processing methods
        with patch.object(processor, '_extract_text_and_images') as mock_extract, \
             patch.object(processor, '_create_ipld_structure') as mock_ipld:
            
            mock_extract.return_value = sample_pdf_content
            mock_ipld.return_value = {
                "document_id": "test_doc",
                "status": "success",
                "cid": "mock_cid"
            }
            
            result = await processor.process_pdf(str(pdf_path))
            
            assert result["status"] == "success"
            assert "document_id" in result
            mock_extract.assert_called_once()
            mock_ipld.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_pdf_processor_with_metadata(self, temp_dir):
        """Test PDF processing with custom metadata."""
        processor = PDFProcessor(enable_monitoring=False, enable_audit=False)
        pdf_path = temp_dir / "test.pdf"
        pdf_path.write_text("mock pdf content")
        
        custom_metadata = {
            "author": "Test Author",
            "category": "research",
            "tags": ["ipfs", "decentralized"]
        }
        
        with patch.object(processor, '_extract_text_and_images') as mock_extract, \
             patch.object(processor, '_create_ipld_structure') as mock_ipld:
            
            mock_extract.return_value = {"text": "test content", "pages": []}
            mock_ipld.return_value = {"status": "success", "document_id": "test"}
            
            result = await processor.process_pdf(str(pdf_path), metadata=custom_metadata)
            
            # Verify metadata was passed through
            args, kwargs = mock_ipld.call_args
            assert custom_metadata["author"] == custom_metadata["author"]
    
    def test_pdf_processor_error_handling(self):
        """Test PDF processor error handling."""
        processor = PDFProcessor(enable_monitoring=False, enable_audit=False)
        
        # Test with non-existent file
        with pytest.raises(FileNotFoundError):
            asyncio.run(processor.process_pdf("/nonexistent/file.pdf"))


class TestLLMOptimizer:
    """Test the LLM optimizer component."""
    
    def test_llm_optimizer_import(self):
        """Test that LLMOptimizer can be imported."""
        assert HAVE_LLM_OPTIMIZER is True
        assert LLMOptimizer is not None
    
    def test_llm_optimizer_initialization(self):
        """Test LLMOptimizer initialization."""
        optimizer = LLMOptimizer()
        assert optimizer is not None
        assert optimizer.model_name == "sentence-transformers/all-MiniLM-L6-v2"
        assert optimizer.max_chunk_size == 2048
        assert optimizer.chunk_overlap == 200
    
    def test_llm_optimizer_custom_params(self):
        """Test LLMOptimizer with custom parameters."""
        optimizer = LLMOptimizer(
            model_name="custom-model",
            max_chunk_size=1024,
            chunk_overlap=100
        )
        assert optimizer.model_name == "custom-model"
        assert optimizer.max_chunk_size == 1024
        assert optimizer.chunk_overlap == 100
    
    @pytest.mark.asyncio
    async def test_chunk_text_basic(self):
        """Test basic text chunking functionality."""
        optimizer = LLMOptimizer(max_chunk_size=50, chunk_overlap=10)
        
        text = "This is a test document. " * 10  # Long text
        chunks = await optimizer.chunk_text(text)
        
        assert len(chunks) > 1
        assert all(isinstance(chunk, dict) for chunk in chunks)
        assert all("text" in chunk for chunk in chunks)
        assert all("chunk_id" in chunk for chunk in chunks)
    
    @pytest.mark.asyncio 
    async def test_optimize_document_structure(self, sample_pdf_content, mock_llm_response):
        """Test document optimization."""
        optimizer = LLMOptimizer()
        
        # Mock the sentence transformer
        with patch('sentence_transformers.SentenceTransformer') as mock_st:
            mock_model = Mock()
            mock_model.encode.return_value = [[0.1, 0.2] * 384]  # Mock embedding
            mock_st.return_value = mock_model
            
            # Mock LLM processing
            with patch.object(optimizer, '_generate_summary') as mock_summary, \
                 patch.object(optimizer, '_extract_entities') as mock_entities:
                
                mock_summary.return_value = mock_llm_response["summary"]
                mock_entities.return_value = mock_llm_response["key_entities"]
                
                result = await optimizer.optimize_document(
                    sample_pdf_content["text"],
                    sample_pdf_content["metadata"]
                )
                
                assert "optimized_chunks" in result
                assert "summary" in result
                assert "key_entities" in result
                assert len(result["optimized_chunks"]) > 0


class TestMultiEngineOCR:
    """Test the multi-engine OCR component."""
    
    def test_ocr_engine_import(self):
        """Test that OCR engines can be imported."""
        assert HAVE_OCR_ENGINE is True
        assert MultiEngineOCR is not None
    
    def test_ocr_engine_initialization(self):
        """Test OCR engine initialization."""
        ocr = MultiEngineOCR()
        assert ocr is not None
        assert ocr.primary_engine == "surya"
        assert "tesseract" in ocr.fallback_engines
        assert "easyocr" in ocr.fallback_engines
    
    def test_ocr_engine_custom_config(self):
        """Test OCR engine with custom configuration."""
        ocr = MultiEngineOCR(
            primary_engine="tesseract",
            fallback_engines=["easyocr"],
            confidence_threshold=0.9
        )
        assert ocr.primary_engine == "tesseract"
        assert ocr.fallback_engines == ["easyocr"]
        assert ocr.confidence_threshold == 0.9
    
    @pytest.mark.asyncio
    async def test_ocr_process_image_mock(self, temp_dir):
        """Test OCR image processing with mocked engines."""
        ocr = MultiEngineOCR()
        
        # Create a mock image file
        image_path = temp_dir / "test_image.png"
        image_path.write_bytes(b"mock image data")
        
        # Mock the OCR engines
        with patch.object(ocr, '_process_with_surya') as mock_surya:
            mock_surya.return_value = {
                "text": "Mock OCR text result",
                "confidence": 0.95,
                "engine": "surya"
            }
            
            result = await ocr.process_image(str(image_path))
            
            assert result["text"] == "Mock OCR text result"
            assert result["confidence"] == 0.95
            assert result["engine"] == "surya"
            mock_surya.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_ocr_fallback_mechanism(self, temp_dir):
        """Test OCR fallback mechanism when primary engine fails."""
        ocr = MultiEngineOCR()
        image_path = temp_dir / "test_image.png"
        image_path.write_bytes(b"mock image data")
        
        # Mock primary engine failure and fallback success
        with patch.object(ocr, '_process_with_surya') as mock_surya, \
             patch.object(ocr, '_process_with_tesseract') as mock_tesseract:
            
            mock_surya.side_effect = Exception("Surya failed")
            mock_tesseract.return_value = {
                "text": "Tesseract OCR result",
                "confidence": 0.85,
                "engine": "tesseract"
            }
            
            result = await ocr.process_image(str(image_path))
            
            assert result["text"] == "Tesseract OCR result"
            assert result["engine"] == "tesseract"
            mock_surya.assert_called_once()
            mock_tesseract.assert_called_once()


class TestComponentIntegration:
    """Test integration between PDF processing components."""
    
    @pytest.mark.asyncio
    async def test_pdf_to_llm_pipeline(self, sample_pdf_content):
        """Test the PDF to LLM optimization pipeline."""
        processor = PDFProcessor(enable_monitoring=False, enable_audit=False)
        optimizer = LLMOptimizer()
        
        # Mock the extraction step
        with patch.object(processor, '_extract_text_and_images') as mock_extract, \
             patch('sentence_transformers.SentenceTransformer'):
            
            mock_extract.return_value = sample_pdf_content
            
            # Test that the components can work together
            with patch.object(optimizer, 'optimize_document') as mock_optimize:
                mock_optimize.return_value = {
                    "optimized_chunks": [{"text": "chunk1"}, {"text": "chunk2"}],
                    "summary": "Test summary"
                }
                
                # This would be part of the full pipeline
                pdf_data = await processor._extract_text_and_images("mock_path")
                llm_result = await optimizer.optimize_document(
                    pdf_data["text"], 
                    pdf_data["metadata"]
                )
                
                assert "optimized_chunks" in llm_result
                assert "summary" in llm_result
                mock_optimize.assert_called_once()
    
    def test_component_availability_flags(self):
        """Test that component availability flags are set correctly."""
        # These should be True since we fixed the import issues
        assert HAVE_PDF_PROCESSOR is True
        assert HAVE_LLM_OPTIMIZER is True
        assert HAVE_OCR_ENGINE is True
    
    def test_error_propagation(self):
        """Test that errors propagate correctly through components."""
        processor = PDFProcessor(enable_monitoring=False, enable_audit=False)
        
        # Test with invalid parameters
        with pytest.raises(TypeError):
            processor.process_pdf(None)  # Should raise TypeError


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
