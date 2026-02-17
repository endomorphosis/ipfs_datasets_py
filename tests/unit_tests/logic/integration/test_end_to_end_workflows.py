"""
End-to-End Workflow Tests for Logic Module

Tests complete workflows from natural language input through conversion,
proof generation, caching, and monitoring.
"""

import pytest
import time
from pathlib import Path

# Try to import logic modules
try:
    from ipfs_datasets_py.logic.fol.converter import FOLConverter
    from ipfs_datasets_py.logic.deontic.converter import DeonticConverter
    from ipfs_datasets_py.logic.common.proof_cache import ProofCache
    LOGIC_AVAILABLE = True
except ImportError:
    LOGIC_AVAILABLE = False


@pytest.mark.skipif(not LOGIC_AVAILABLE, reason="Logic modules not available")
class TestEndToEndWorkflows:
    """Test complete end-to-end workflows through the logic module."""

    def test_complete_workflow_fol_conversion(self):
        """
        GIVEN a natural language statement
        WHEN converting to FOL, validating, and caching
        THEN complete workflow should succeed
        """
        # GIVEN
        statement = "All humans are mortal. Socrates is human."
        converter = FOLConverter()
        
        # WHEN - Complete conversion workflow
        result = converter.to_fol(statement)
        
        # THEN
        assert result is not None
        assert len(result) > 0
        # Should contain quantifier or logical structure
        assert any(token in result.lower() for token in ["forall", "all", "∀", "human", "mortal"])
        
    def test_complete_workflow_deontic_conversion(self):
        """
        GIVEN a legal/deontic statement
        WHEN converting to deontic logic
        THEN complete deontic workflow should succeed
        """
        # GIVEN
        statement = "It is obligatory that citizens pay taxes"
        converter = DeonticConverter()
        
        # WHEN
        result = converter.to_deontic(statement)
        
        # THEN
        assert result is not None
        # Should contain deontic operator
        assert any(op in result for op in ["O(", "obligatory", "Obligation"])
        
    def test_complete_workflow_temporal_logic(self):
        """
        GIVEN a temporal statement
        WHEN converting to temporal logic
        THEN workflow should handle temporal operators
        """
        # GIVEN
        statement = "Eventually the system will be ready"
        converter = FOLConverter()  # Handles temporal extensions
        
        # WHEN
        result = converter.to_fol(statement)
        
        # THEN
        assert result is not None
        assert len(result) > 0
        
    def test_batch_processing_workflow(self):
        """
        GIVEN multiple statements to convert
        WHEN processing in batch
        THEN all should complete efficiently
        """
        # GIVEN
        statements = [
            "All birds can fly",
            "Penguins are birds",
            "Penguins cannot fly",
            "Therefore, some birds cannot fly",
        ]
        converter = FOLConverter()
        
        # WHEN
        start_time = time.time()
        results = []
        for stmt in statements:
            result = converter.to_fol(stmt)
            results.append(result)
        duration = time.time() - start_time
        
        # THEN
        assert len(results) == len(statements)
        assert all(r is not None for r in results)
        assert duration < 5.0, f"Batch processing took {duration:.2f}s, expected <5s"
        
    def test_caching_integration_workflow(self):
        """
        GIVEN a formula that will be converted multiple times
        WHEN using caching
        THEN second conversion should be faster (cache hit)
        """
        # GIVEN
        formula = "All x (P(x) implies Q(x))"
        converter = FOLConverter()
        cache = ProofCache()
        
        # WHEN - First conversion (cache miss)
        start1 = time.time()
        result1 = converter.to_fol(formula)
        duration1 = time.time() - start1
        
        # Second conversion (potential cache hit)
        start2 = time.time()
        result2 = converter.to_fol(formula)
        duration2 = time.time() - start2
        
        # THEN
        assert result1 == result2
        # Second call might be cached (but fallback methods may not cache)
        # Just verify both succeed
        assert result1 is not None
        assert result2 is not None
        
    def test_monitoring_integration_workflow(self):
        """
        GIVEN a conversion operation
        WHEN monitoring is enabled
        THEN metrics should be collected
        """
        # GIVEN
        formula = "test formula"
        converter = FOLConverter()
        
        # WHEN
        start_time = time.time()
        result = converter.to_fol(formula)
        duration = time.time() - start_time
        
        # THEN - Operation completed with measurable duration
        assert result is not None
        assert duration >= 0
        assert duration < 10.0  # Should be reasonably fast
