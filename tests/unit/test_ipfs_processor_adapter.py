"""
Unit tests for IPFSProcessorAdapter.

Tests the IPFS adapter's ability to detect, fetch, and process IPFS content.
"""

import pytest
from pathlib import Path
from ipfs_datasets_py.processors.adapters.ipfs_adapter import IPFSProcessorAdapter
from ipfs_datasets_py.processors.protocol import InputType, ProcessingStatus


class TestIPFSProcessorAdapter:
    """Test IPFSProcessorAdapter functionality."""
    
    @pytest.fixture
    def adapter(self):
        """Create adapter instance."""
        return IPFSProcessorAdapter()
    
    # CID Detection Tests
    
    def test_is_cid_v0_valid(self, adapter):
        """Test CIDv0 detection with valid CID."""
        # GIVEN a valid CIDv0 (Qm + 44 base58 characters)
        cid = "QmXoypizjW3WknFiJnKLwHCnL72vedxjQkDDP1mXWo6uco"  # Example CID
        
        # WHEN checking if it's a CID
        result = adapter._is_cid(cid)
        
        # THEN it should be detected as valid
        assert result is True
    
    def test_is_cid_v1_valid(self, adapter):
        """Test CIDv1 detection with valid CID."""
        # GIVEN a valid CIDv1 (b + base32)
        cid = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
        
        # WHEN checking if it's a CID
        result = adapter._is_cid(cid)
        
        # THEN it should be detected as valid
        assert result is True
    
    def test_is_cid_invalid(self, adapter):
        """Test CID detection with invalid input."""
        # GIVEN various invalid inputs
        invalid_inputs = [
            "not-a-cid",
            "https://example.com",
            "QmInvalid",  # Too short
            "bInvalid",  # Too short
            "12345",
            ""
        ]
        
        # WHEN checking each
        for invalid in invalid_inputs:
            result = adapter._is_cid(invalid)
            
            # THEN they should not be detected as CIDs
            assert result is False, f"'{invalid}' should not be a valid CID"
    
    # CID Extraction Tests
    
    def test_extract_cid_direct(self, adapter):
        """Test CID extraction from direct CID."""
        # GIVEN a direct CID
        cid = "QmXoypizjW3WknFiJnKLwHCnL72vedxjQkDDP1mXWo6uco"
        
        # WHEN extracting CID
        result = adapter._extract_cid(cid)
        
        # THEN it should return the CID
        assert result == cid
    
    def test_extract_cid_from_ipfs_url(self, adapter):
        """Test CID extraction from ipfs:// URL."""
        # GIVEN an ipfs:// URL
        cid = "QmXoypizjW3WknFiJnKLwHCnL72vedxjQkDDP1mXWo6uco"
        url = f"ipfs://{cid}"
        
        # WHEN extracting CID
        result = adapter._extract_cid(url)
        
        # THEN it should return the CID
        assert result == cid
    
    def test_extract_cid_from_ipfs_path(self, adapter):
        """Test CID extraction from /ipfs/ path."""
        # GIVEN an /ipfs/ path
        cid = "QmXoypizjW3WknFiJnKLwHCnL72vedxjQkDDP1mXWo6uco"
        path = f"/ipfs/{cid}"
        
        # WHEN extracting CID
        result = adapter._extract_cid(path)
        
        # THEN it should return the CID
        assert result == cid
    
    def test_extract_cid_from_ipfs_path_with_subpath(self, adapter):
        """Test CID extraction from /ipfs/ path with subpath."""
        # GIVEN an /ipfs/ path with subpath
        cid = "QmXoypizjW3WknFiJnKLwHCnL72vedxjQkDDP1mXWo6uco"
        path = f"/ipfs/{cid}/subpath/file.txt"
        
        # WHEN extracting CID
        result = adapter._extract_cid(path)
        
        # THEN it should return just the CID
        assert result == cid
    
    def test_extract_cid_invalid(self, adapter):
        """Test CID extraction from invalid input."""
        # GIVEN invalid inputs
        invalid = "https://example.com/not-ipfs"
        
        # WHEN extracting CID
        result = adapter._extract_cid(invalid)
        
        # THEN it should return None
        assert result is None
    
    # can_process Tests
    
    @pytest.mark.asyncio
    async def test_can_process_ipfs_url(self, adapter):
        """Test can_process with ipfs:// URL."""
        # GIVEN an ipfs:// URL
        url = "ipfs://QmXoypizjW3WknFiJnKLwHCnL72vedxjQkDDP1mXWo6uco"
        
        # WHEN checking if it can process
        result = await adapter.can_process(url)
        
        # THEN it should return True
        assert result is True
    
    @pytest.mark.asyncio
    async def test_can_process_ipfs_path(self, adapter):
        """Test can_process with /ipfs/ path."""
        # GIVEN an /ipfs/ path
        path = "/ipfs/QmXoypizjW3WknFiJnKLwHCnL72vedxjQkDDP1mXWo6uco"
        
        # WHEN checking if it can process
        result = await adapter.can_process(path)
        
        # THEN it should return True
        assert result is True
    
    @pytest.mark.asyncio
    async def test_can_process_cid(self, adapter):
        """Test can_process with direct CID."""
        # GIVEN a CID
        cid = "QmXoypizjW3WknFiJnKLwHCnL72vedxjQkDDP1mXWo6uco"
        
        # WHEN checking if it can process
        result = await adapter.can_process(cid)
        
        # THEN it should return True
        assert result is True
    
    @pytest.mark.asyncio
    async def test_can_process_ipns(self, adapter):
        """Test can_process with ipns:// URL."""
        # GIVEN an ipns:// URL
        url = "ipns://example.com"
        
        # WHEN checking if it can process
        result = await adapter.can_process(url)
        
        # THEN it should return True
        assert result is True
    
    @pytest.mark.asyncio
    async def test_can_process_non_ipfs(self, adapter):
        """Test can_process with non-IPFS input."""
        # GIVEN non-IPFS inputs
        non_ipfs = [
            "https://example.com",
            "document.pdf",
            "/path/to/file.txt"
        ]
        
        # WHEN checking each
        for input_source in non_ipfs:
            result = await adapter.can_process(input_source)
            
            # THEN they should return False
            assert result is False, f"'{input_source}' should not be processable by IPFS adapter"
    
    # Metadata Tests
    
    def test_get_supported_types(self, adapter):
        """Test supported types."""
        # WHEN getting supported types
        types = adapter.get_supported_types()
        
        # THEN it should include IPFS types
        assert "ipfs" in types
        assert "cid" in types
        assert "ipns" in types
    
    def test_get_priority(self, adapter):
        """Test priority."""
        # WHEN getting priority
        priority = adapter.get_priority()
        
        # THEN it should be highest (20)
        assert priority == 20
    
    def test_get_name(self, adapter):
        """Test name."""
        # WHEN getting name
        name = adapter.get_name()
        
        # THEN it should be correct
        assert name == "IPFSProcessorAdapter"
    
    # Integration Test (will fail without IPFS daemon, but structure is correct)
    
    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires IPFS daemon or gateway access")
    async def test_process_ipfs_content(self, adapter):
        """
        Test processing IPFS content.
        
        This test requires either:
        - Local IPFS daemon running
        - Gateway access
        - Mock IPFS client
        """
        # GIVEN a valid IPFS CID (known content)
        cid = "QmXoypizjW3WknFiJnKLwHCnL72vedxjQkDDP1mXWo6uco"
        
        # WHEN processing it
        result = await adapter.process(cid, gateway_fallback=True)
        
        # THEN we should get a result
        assert result is not None
        assert result.metadata.input_type == InputType.IPFS
        assert 'ipfs_cid' in result.metadata.resource_usage
        
        # AND knowledge graph should include IPFS entity
        ipfs_entities = [
            e for e in result.knowledge_graph.entities
            if e.type == "IPFSContent"
        ]
        assert len(ipfs_entities) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
