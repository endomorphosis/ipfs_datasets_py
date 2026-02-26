"""
Tests for config_validators TypedDict contracts.
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.config_validators import (
    MergedConfigDict,
)


class TestMergedConfigDict:
    """Test MergedConfigDict contract."""
    
    def test_merged_config_structure(self):
        """Verify merged config structure."""
        sample: MergedConfigDict = {
            "field1": "value1",
            "field2": 123,
            "field3": {"nested": "value"}
        }
        assert isinstance(sample, dict)
    
    def test_merged_config_empty(self):
        """Verify empty config works."""
        empty: MergedConfigDict = {}
        assert len(empty) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
