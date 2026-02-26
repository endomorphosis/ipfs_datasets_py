"""
Tests for llm_optimizer TypedDict contracts.
"""

import pytest
from ipfs_datasets_py.processors.llm_optimizer import (
    ClassifiedContentDict,
)


class TestClassifiedContentDict:
    """Test ClassifiedContentDict contract."""
    
    def test_classified_content_structure(self):
        """Verify classified content structure."""
        sample: ClassifiedContentDict = {
            "classification": "technical",
            "confidence": 0.95,
            "sub_classifications": ["paper", "academic"],
            "metadata": {"source": "pdf"},
            "processing_time": 0.5
        }
        assert isinstance(sample.get("classification"), (str, type(None)))
        assert isinstance(sample.get("confidence"), (float, type(None)))
    
    def test_classified_content_types(self):
        """Verify field types."""
        sample: ClassifiedContentDict = {
            "confidence": 0.8,
            "sub_classifications": ["type1"],
            "metadata": {"field": "value"}
        }
        assert isinstance(sample.get("confidence"), (float, type(None)))
        assert isinstance(sample.get("sub_classifications"), (list, type(None)))
        assert isinstance(sample.get("metadata"), (dict, type(None)))
    
    def test_classified_content_confidence_range(self):
        """Verify confidence value range."""
        sample: ClassifiedContentDict = {
            "confidence": 0.5
        }
        conf = sample.get("confidence")
        if conf is not None:
            assert 0 <= conf <= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
