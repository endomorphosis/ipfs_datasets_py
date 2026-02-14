"""
Tests for FOLConverter - Unified converter with integrated features.
"""

import pytest
from ipfs_datasets_py.logic.fol import FOLConverter
from ipfs_datasets_py.logic.common.converters import ConversionStatus


class TestFOLConverter:
    """Test FOLConverter class."""
    
    def test_converter_initialization(self):
        """Test that converter can be initialized with default settings."""
        converter = FOLConverter()
        assert converter is not None
        # use_nlp may be False if spaCy is not installed (uses regex fallback)
        assert isinstance(converter.use_nlp, bool)
        assert isinstance(converter.enable_monitoring, bool)
        assert converter.confidence_threshold == 0.7
    
    def test_converter_initialization_with_options(self):
        """Test converter initialization with custom options."""
        converter = FOLConverter(
            use_cache=False,
            use_ml=False,
            use_nlp=False,
            enable_monitoring=False,
            confidence_threshold=0.5
        )
        assert converter.enable_caching is False
        assert converter.use_ml is False
        assert converter.use_nlp is False
        assert converter.enable_monitoring is False
        assert converter.confidence_threshold == 0.5
    
    def test_simple_conversion(self):
        """Test simple text to FOL conversion."""
        converter = FOLConverter(use_ml=False, use_nlp=False, enable_monitoring=False)
        
        result = converter.convert("All humans are mortal")
        
        assert result is not None
        assert result.success is True
        assert result.output is not None
        assert result.output.formula_string is not None
        assert len(result.output.formula_string) > 0
    
    def test_validation_empty_input(self):
        """Test that empty input is rejected."""
        converter = FOLConverter(use_ml=False, use_nlp=False, enable_monitoring=False)
        
        result = converter.convert("")
        
        assert result.success is False
        assert len(result.errors) > 0
        assert "empty" in result.errors[0].lower()
    
    def test_validation_whitespace_input(self):
        """Test that whitespace-only input is rejected."""
        converter = FOLConverter(use_ml=False, use_nlp=False, enable_monitoring=False)
        
        result = converter.convert("   ")
        
        assert result.success is False
        assert len(result.errors) > 0
    
    def test_caching(self):
        """Test that caching works."""
        converter = FOLConverter(use_cache=True, use_ml=False, use_nlp=False, enable_monitoring=False)
        
        # First conversion
        result1 = converter.convert("P implies Q")
        assert result1.status == ConversionStatus.SUCCESS
        
        # Second conversion should be cached
        result2 = converter.convert("P implies Q")
        assert result2.status == ConversionStatus.CACHED
        
        # Check cache stats
        stats = converter.get_cache_stats()
        assert stats["cache_size"] > 0
    
    def test_batch_conversion(self):
        """Test batch conversion."""
        converter = FOLConverter(use_ml=False, use_nlp=False, enable_monitoring=False)
        
        texts = [
            "All humans are mortal",
            "Socrates is human",
            "Therefore Socrates is mortal"
        ]
        
        results = converter.convert_batch(texts, max_workers=2)
        
        assert len(results) == 3
        # At least some should succeed
        successful = [r for r in results if r.success]
        assert len(successful) > 0
    
    @pytest.mark.asyncio
    async def test_async_conversion(self):
        """Test async conversion interface."""
        converter = FOLConverter(use_ml=False, use_nlp=False, enable_monitoring=False)
        
        result = await converter.convert_async("All X are Y")
        
        assert result is not None
        assert result.output is not None
    
    def test_confidence_calculation(self):
        """Test that confidence is calculated."""
        converter = FOLConverter(use_ml=False, use_nlp=False, enable_monitoring=False)
        
        result = converter.convert("All humans are mortal")
        
        assert result.success is True
        assert result.output.confidence > 0
        assert result.output.confidence <= 1.0
    
    def test_metadata_included(self):
        """Test that metadata is included in results."""
        converter = FOLConverter(use_ml=False, use_nlp=False, enable_monitoring=False)
        
        result = converter.convert("P and Q")
        
        assert result.success is True
        assert result.output.metadata is not None
        assert "source_text" in result.output.metadata
        assert "conversion_time_ms" in result.output.metadata
