"""
Tests for IPFS CID-based cache utilities.

This module tests the cache_utils functions that generate and validate
IPFS Content Identifiers (CIDs) for cache keys.
"""

import pytest
from ipfs_datasets_py.logic.TDFOL.nl.cache_utils import (
    create_cache_cid,
    validate_cid,
    parse_cid,
    MULTIFORMATS_AVAILABLE
)


class TestCreateCacheCID:
    """Tests for create_cache_cid function."""
    
    def test_create_cid_basic(self):
        """Test creating a basic CID from cache data."""
        # GIVEN cache data
        data = {
            "text": "hello world",
            "provider": "openai",
            "prompt_hash": "abc123"
        }
        
        # WHEN creating a CID
        cid = create_cache_cid(data)
        
        # THEN it should be a valid CIDv1
        assert isinstance(cid, str)
        assert cid.startswith("bafk")  # CIDv1 with base32
        assert len(cid) > 50  # CIDs are longer than regular hashes
    
    def test_cid_determinism(self):
        """Test that same input produces same CID."""
        # GIVEN same cache data
        data = {
            "text": "test text",
            "provider": "anthropic",
            "prompt_hash": "xyz789"
        }
        
        # WHEN creating CIDs multiple times
        cid1 = create_cache_cid(data)
        cid2 = create_cache_cid(data)
        cid3 = create_cache_cid(data)
        
        # THEN all CIDs should be identical
        assert cid1 == cid2
        assert cid2 == cid3
    
    def test_cid_uniqueness(self):
        """Test that different inputs produce different CIDs."""
        # GIVEN different cache data
        data1 = {"text": "text1", "provider": "openai", "prompt_hash": "hash1"}
        data2 = {"text": "text2", "provider": "openai", "prompt_hash": "hash1"}
        data3 = {"text": "text1", "provider": "anthropic", "prompt_hash": "hash1"}
        
        # WHEN creating CIDs
        cid1 = create_cache_cid(data1)
        cid2 = create_cache_cid(data2)
        cid3 = create_cache_cid(data3)
        
        # THEN all CIDs should be different
        assert cid1 != cid2
        assert cid2 != cid3
        assert cid1 != cid3
    
    def test_cid_key_order_independence(self):
        """Test that dictionary key order doesn't affect CID."""
        # GIVEN same data in different key orders
        data1 = {"text": "hello", "provider": "openai", "prompt_hash": "abc"}
        data2 = {"prompt_hash": "abc", "text": "hello", "provider": "openai"}
        data3 = {"provider": "openai", "prompt_hash": "abc", "text": "hello"}
        
        # WHEN creating CIDs
        cid1 = create_cache_cid(data1)
        cid2 = create_cache_cid(data2)
        cid3 = create_cache_cid(data3)
        
        # THEN all CIDs should be identical (deterministic)
        assert cid1 == cid2
        assert cid2 == cid3
    
    def test_cid_with_special_characters(self):
        """Test CID generation with special characters."""
        # GIVEN data with special characters
        data = {
            "text": "All contractors ∀x must pay taxes",
            "provider": "openai",
            "prompt_hash": "unicode→test"
        }
        
        # WHEN creating a CID
        cid = create_cache_cid(data)
        
        # THEN it should still produce a valid CID
        assert cid.startswith("bafk")
        assert validate_cid(cid)
    
    def test_cid_with_nested_data(self):
        """Test CID generation with nested structures."""
        # GIVEN nested data
        data = {
            "text": "test",
            "provider": "openai",
            "prompt_hash": "abc",
            "metadata": {
                "version": "1.0",
                "options": ["opt1", "opt2"]
            }
        }
        
        # WHEN creating a CID
        cid = create_cache_cid(data)
        
        # THEN it should produce a valid CID
        assert cid.startswith("bafk")
        assert validate_cid(cid)
    
    def test_cid_empty_strings(self):
        """Test CID generation with empty strings."""
        # GIVEN data with empty strings
        data = {
            "text": "",
            "provider": "",
            "prompt_hash": ""
        }
        
        # WHEN creating a CID
        cid = create_cache_cid(data)
        
        # THEN it should still produce a valid CID
        assert cid.startswith("bafk")
        assert validate_cid(cid)


class TestValidateCID:
    """Tests for validate_cid function."""
    
    def test_validate_valid_cid(self):
        """Test validation of a valid CID."""
        # GIVEN a valid CID
        data = {"text": "test", "provider": "openai", "prompt_hash": "abc"}
        cid = create_cache_cid(data)
        
        # WHEN validating
        is_valid = validate_cid(cid)
        
        # THEN it should be valid
        assert is_valid is True
    
    def test_validate_invalid_cid(self):
        """Test validation of invalid CID strings."""
        # GIVEN invalid CID strings
        invalid_cids = [
            "not_a_cid",
            "bafk_incomplete",
            "12345678",
            "",
            "QmInvalidCIDv0Format"
        ]
        
        # WHEN validating each
        results = [validate_cid(cid) for cid in invalid_cids]
        
        # THEN all should be invalid
        assert all(result is False for result in results)
    
    def test_validate_cidv0(self):
        """Test that CIDv0 format is also valid."""
        # GIVEN a CIDv0 (starts with Qm)
        # Note: CIDv0 uses base58btc and dag-pb codec
        cidv0 = "QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG"
        
        # WHEN validating
        is_valid = validate_cid(cidv0)
        
        # THEN it should be valid
        assert is_valid is True


class TestParseCID:
    """Tests for parse_cid function."""
    
    def test_parse_cid_structure(self):
        """Test parsing CID structure."""
        # GIVEN a CID
        data = {"text": "test", "provider": "openai", "prompt_hash": "abc"}
        cid = create_cache_cid(data)
        
        # WHEN parsing
        info = parse_cid(cid)
        
        # THEN it should have correct structure
        assert "version" in info
        assert "codec" in info
        assert "hashfun" in info
        
        assert info["version"] == 1
        assert info["codec"] == "raw"
        
        # Check hashfun structure
        assert "name" in info["hashfun"]
        assert "digest" in info["hashfun"]
        assert info["hashfun"]["name"] == "sha2-256"
    
    def test_parse_invalid_cid(self):
        """Test parsing invalid CID raises error."""
        # GIVEN an invalid CID
        invalid_cid = "not_a_valid_cid"
        
        # WHEN parsing
        # THEN it should raise ValueError
        with pytest.raises(ValueError, match="Invalid CID"):
            parse_cid(invalid_cid)
    
    def test_parse_cid_digest(self):
        """Test that parsed CID contains digest information."""
        # GIVEN a CID
        data = {"text": "hello", "provider": "openai", "prompt_hash": "xyz"}
        cid = create_cache_cid(data)
        
        # WHEN parsing
        info = parse_cid(cid)
        
        # THEN digest should be present and hex-encoded
        digest = info["hashfun"]["digest"]
        assert isinstance(digest, str)
        # Digest includes multihash prefix (2 bytes) + SHA-256 hash (32 bytes) = 68 hex chars
        assert len(digest) > 60
        assert all(c in "0123456789abcdef" for c in digest)


class TestCacheIntegration:
    """Integration tests for cache CID usage."""
    
    def test_cid_as_dict_key(self):
        """Test that CIDs work as dictionary keys."""
        # GIVEN a cache dictionary and some CIDs
        cache = {}
        data1 = {"text": "test1", "provider": "openai", "prompt_hash": "a"}
        data2 = {"text": "test2", "provider": "openai", "prompt_hash": "b"}
        
        cid1 = create_cache_cid(data1)
        cid2 = create_cache_cid(data2)
        
        # WHEN using CIDs as keys
        cache[cid1] = ("formula1", 0.9)
        cache[cid2] = ("formula2", 0.8)
        
        # THEN we can retrieve values by CID
        assert cache[cid1] == ("formula1", 0.9)
        assert cache[cid2] == ("formula2", 0.8)
        
        # AND regenerating the same CID retrieves the same value
        cid1_again = create_cache_cid(data1)
        assert cache[cid1_again] == ("formula1", 0.9)
    
    def test_cid_collision_resistance(self):
        """Test that similar inputs produce different CIDs."""
        # GIVEN very similar cache data
        similar_data = [
            {"text": "test", "provider": "openai", "prompt_hash": "a"},
            {"text": "test", "provider": "openai", "prompt_hash": "b"},
            {"text": "test", "provider": "anthropic", "prompt_hash": "a"},
            {"text": "test2", "provider": "openai", "prompt_hash": "a"},
        ]
        
        # WHEN creating CIDs
        cids = [create_cache_cid(data) for data in similar_data]
        
        # THEN all CIDs should be unique
        assert len(cids) == len(set(cids))  # No duplicates
    
    def test_cid_reproducibility_across_runs(self):
        """Test that CIDs are reproducible across multiple runs."""
        # GIVEN the same data
        data = {
            "text": "reproducibility test",
            "provider": "openai",
            "prompt_hash": "consistent_hash"
        }
        
        # WHEN creating CIDs in separate "runs"
        cids = [create_cache_cid(data) for _ in range(10)]
        
        # THEN all CIDs should be identical
        assert len(set(cids)) == 1  # Only one unique CID
        assert all(cid == cids[0] for cid in cids)


@pytest.mark.skipif(not MULTIFORMATS_AVAILABLE, reason="multiformats not installed")
class TestMultiformatsIntegration:
    """Tests requiring multiformats library."""
    
    def test_cid_can_be_decoded(self):
        """Test that generated CIDs can be decoded by multiformats."""
        from multiformats import CID
        
        # GIVEN a CID
        data = {"text": "decode test", "provider": "openai", "prompt_hash": "xyz"}
        cid_str = create_cache_cid(data)
        
        # WHEN decoding with multiformats library
        cid = CID.decode(cid_str)
        
        # THEN it should decode successfully
        assert cid.version == 1
        codec_name = cid.codec.name if hasattr(cid.codec, 'name') else str(cid.codec)
        assert codec_name == "raw"
        hashfun_name = cid.hashfun.name if hasattr(cid.hashfun, 'name') else str(cid.hashfun)
        assert hashfun_name == "sha2-256"
    
    def test_cid_base_encoding(self):
        """Test that CIDs use base32 encoding."""
        from multiformats import CID
        
        # GIVEN a CID
        data = {"text": "base test", "provider": "openai", "prompt_hash": "abc"}
        cid_str = create_cache_cid(data)
        
        # WHEN checking the base
        cid = CID.decode(cid_str)
        
        # THEN it should use base32
        # CIDv1 with base32 starts with 'b'
        assert cid_str.startswith("bafk")  # base32 + raw codec


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
