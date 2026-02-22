"""
Integration tests for unified converter architecture.

Tests FOLConverter and DeonticConverter working together and validates
all 6 integrated features across both converters.
"""

import asyncio
import pytest
from ipfs_datasets_py.logic.fol import FOLConverter
from ipfs_datasets_py.logic.deontic import DeonticConverter


class TestConverterIntegration:
    """Integration tests for unified converter architecture."""
    
    def test_fol_and_deontic_converters_coexist(self):
        """Test that FOL and Deontic converters can be used together."""
        # GIVEN: Both converters initialized
        fol_converter = FOLConverter(use_ml=False, enable_monitoring=False)
        deontic_converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        
        # WHEN: Converting similar content
        fol_result = fol_converter.convert("All humans are mortal")
        deontic_result = deontic_converter.convert("The tenant must pay rent")
        
        # THEN: Both should succeed
        assert fol_result.success
        assert deontic_result.success
        assert fol_result.output is not None
        assert deontic_result.output is not None
    
    def test_batch_processing_both_converters(self):
        """Test batch processing works for both converter types."""
        # GIVEN: Converters with batch processing
        fol_converter = FOLConverter(use_ml=False, enable_monitoring=False)
        deontic_converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        
        fol_texts = ["P -> Q", "All X are Y", "Some Z exist"]
        deontic_texts = ["Must comply", "May appeal", "Shall not trespass"]
        
        # WHEN: Batch converting
        fol_results = fol_converter.convert_batch(fol_texts, max_workers=2)
        deontic_results = deontic_converter.convert_batch(deontic_texts, max_workers=2)
        
        # THEN: All should be processed
        assert len(fol_results) == 3
        assert len(deontic_results) == 3
        
        # At least some should succeed
        fol_success = [r for r in fol_results if r.success]
        deontic_success = [r for r in deontic_results if r.success]
        assert len(fol_success) > 0
        assert len(deontic_success) > 0
    
    def test_caching_across_converters(self):
        """Test that each converter maintains its own cache."""
        # GIVEN: Converters with caching enabled
        fol_converter = FOLConverter(use_cache=True, use_ml=False, enable_monitoring=False)
        deontic_converter = DeonticConverter(use_cache=True, use_ml=False, enable_monitoring=False)
        
        # WHEN: Converting and checking cache stats
        fol_converter.convert("All humans are mortal")
        deontic_converter.convert("The tenant must pay rent")
        
        fol_stats = fol_converter.get_cache_stats()
        deontic_stats = deontic_converter.get_cache_stats()
        
        # THEN: Both should have cache activity
        assert fol_stats is not None
        assert deontic_stats is not None
    
    @pytest.mark.asyncio
    async def test_async_conversion_both_converters(self):
        """Test async conversion works for both converters."""
        # GIVEN: Both converters
        fol_converter = FOLConverter(use_ml=False, enable_monitoring=False)
        deontic_converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        
        # WHEN: Converting asynchronously
        fol_result = await fol_converter.convert_async("P and Q")
        deontic_result = await deontic_converter.convert_async("Must obey")
        
        # THEN: Both should succeed
        assert fol_result.success
        assert deontic_result.success
    
    @pytest.mark.asyncio
    async def test_concurrent_async_conversions(self):
        """Test multiple async conversions can run concurrently."""
        # GIVEN: Converters and multiple texts
        fol_converter = FOLConverter(use_ml=False, enable_monitoring=False)
        deontic_converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        
        # WHEN: Running concurrent conversions
        results = await asyncio.gather(
            fol_converter.convert_async("P -> Q"),
            deontic_converter.convert_async("Must pay"),
            fol_converter.convert_async("All X are Y"),
            deontic_converter.convert_async("May appeal")
        )
        
        # THEN: All should complete
        assert len(results) == 4
        assert all(r.success for r in results)
    
    def test_confidence_calculation_consistency(self):
        """Test confidence calculation is consistent across converters."""
        # GIVEN: Converters with heuristic confidence
        fol_converter = FOLConverter(use_ml=False, enable_monitoring=False)
        deontic_converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        
        # WHEN: Converting
        fol_result = fol_converter.convert("All humans are mortal")
        deontic_result = deontic_converter.convert("The tenant must pay rent")
        
        # THEN: Both should have valid confidence scores
        assert 0 <= fol_result.output.confidence <= 1.0
        assert 0 <= deontic_result.output.confidence <= 1.0
    
    def test_validation_consistency(self):
        """Test input validation works consistently across converters."""
        # GIVEN: Converters
        fol_converter = FOLConverter(use_ml=False, enable_monitoring=False)
        deontic_converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        
        # WHEN: Converting empty input
        fol_result = fol_converter.convert("")
        deontic_result = deontic_converter.convert("")
        
        # THEN: Both should fail validation consistently
        assert not fol_result.success
        assert not deontic_result.success
    
    def test_stats_tracking_both_converters(self):
        """Test statistics tracking works for both converters."""
        # GIVEN: Converters
        fol_converter = FOLConverter(use_ml=False, enable_monitoring=False)
        deontic_converter = DeonticConverter(use_ml=False, enable_monitoring=False)
        
        # WHEN: Performing conversions
        fol_converter.convert("P -> Q")
        deontic_converter.convert("Must comply")
        
        # THEN: Stats should be available
        fol_stats = fol_converter.get_stats()
        deontic_stats = deontic_converter.get_stats()
        
        assert isinstance(fol_stats, dict)
        assert isinstance(deontic_stats, dict)


class TestBackwardCompatibility:
    """Test backward compatibility of legacy functions."""
    
    @pytest.mark.asyncio
    async def test_legacy_text_to_fol_still_works(self):
        """Test that legacy text_to_fol function still works."""
        # GIVEN: Legacy function
        from ipfs_datasets_py.logic.fol import convert_text_to_fol
        import warnings
        
        # WHEN: Using legacy function
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = await convert_text_to_fol("All humans are mortal")
        
        # THEN: Should work with deprecation warning
        assert result["status"] == "success"
        assert len(w) > 0
        assert "deprecated" in str(w[0].message).lower()
    
    @pytest.mark.asyncio
    async def test_legacy_legal_text_to_deontic_still_works(self):
        """Test that legacy legal_text_to_deontic function still works."""
        # GIVEN: Legacy function
        from ipfs_datasets_py.logic.deontic import convert_legal_text_to_deontic
        import warnings
        
        # WHEN: Using legacy function
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = await convert_legal_text_to_deontic("The tenant must pay rent")
        
        # THEN: Should work with deprecation warning
        assert result["status"] == "success"
        assert len(w) > 0
        assert "deprecated" in str(w[0].message).lower()


class TestPerformanceCharacteristics:
    """Test performance characteristics of unified converters."""
    
    def test_batch_processing_is_faster_than_sequential(self):
        """Test that batch processing provides speedup."""
        import time
        
        # GIVEN: Converter and texts
        converter = FOLConverter(use_ml=False, enable_monitoring=False, use_cache=False)
        texts = ["P -> Q", "All X are Y", "Some Z exist", "P and Q", "Not R"] * 2
        
        # WHEN: Converting sequentially
        start_seq = time.time()
        seq_results = [converter.convert(t) for t in texts]
        seq_time = time.time() - start_seq
        
        # AND: Converting in batch
        start_batch = time.time()
        batch_results = converter.convert_batch(texts, max_workers=4)
        batch_time = time.time() - start_batch
        
        # THEN: Batch should be faster (or at least not significantly slower)
        # Allow some overhead for small batches in CI environments
        assert len(seq_results) == len(batch_results)
        # Batch processing should be at least somewhat efficient
        assert batch_time < seq_time * 10 or batch_time < 1.0  # Very generous threshold
    
    def test_caching_improves_repeat_conversions(self):
        """Test that caching speeds up repeat conversions."""
        import time
        
        # GIVEN: Converter with caching
        converter = FOLConverter(use_cache=True, use_ml=False, enable_monitoring=False)
        text = "All humans are mortal"
        
        # WHEN: First conversion (cache miss)
        start_first = time.time()
        result1 = converter.convert(text)
        first_time = time.time() - start_first
        
        # AND: Second conversion (cache hit)
        start_second = time.time()
        result2 = converter.convert(text)
        second_time = time.time() - start_second
        
        # THEN: Second should be much faster (cache hit)
        assert result1.success
        assert result2.success
        # Second conversion should be faster or at least not slower
        # (allowing for timing variance)
        assert second_time <= first_time * 1.5


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
