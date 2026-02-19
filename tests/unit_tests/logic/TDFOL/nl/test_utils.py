"""
Tests for TDFOL NL utilities module (consolidated from cache_utils and spacy_utils tests).

This module tests:
- IPFS CID generation and validation for cache keys
- spaCy model loading and error handling
"""

import pytest
from ipfs_datasets_py.logic.TDFOL.nl.utils import (
    create_cache_cid,
    validate_cid,
    parse_cid,
    MULTIFORMATS_AVAILABLE,
    require_spacy,
    load_spacy_model,
    HAVE_SPACY,
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


class TestSpacyUtilities:
    """Tests for spaCy utility functions."""
    
    def test_have_spacy_flag(self):
        """Test that HAVE_SPACY flag is set correctly."""
        # GIVEN the HAVE_SPACY flag
        # THEN it should be a boolean
        assert isinstance(HAVE_SPACY, bool)
    
    @pytest.mark.skipif(not HAVE_SPACY, reason="spaCy not installed")
    def test_require_spacy_succeeds_when_available(self):
        """Test require_spacy succeeds when spaCy is available."""
        # WHEN spaCy is available and we require it
        # THEN it should not raise
        require_spacy()  # Should not raise
    
    @pytest.mark.skipif(HAVE_SPACY, reason="Test requires spaCy to be unavailable")
    def test_require_spacy_fails_when_unavailable(self):
        """Test require_spacy fails when spaCy is not available."""
        # WHEN spaCy is not available and we require it
        # THEN it should raise ImportError
        with pytest.raises(ImportError, match="spaCy is required"):
            require_spacy()
    
    @pytest.mark.skipif(not HAVE_SPACY, reason="spaCy not installed")
    def test_load_spacy_model_success(self):
        """Test loading a spaCy model when available."""
        # GIVEN a valid model name
        model_name = "en_core_web_sm"
        
        # WHEN loading the model
        try:
            nlp = load_spacy_model(model_name)
            
            # THEN it should return a valid language model
            assert nlp is not None
            assert hasattr(nlp, 'pipe')
            assert hasattr(nlp, 'vocab')
        except OSError:
            # Model not downloaded, skip test
            pytest.skip(f"spaCy model {model_name} not downloaded")
    
    @pytest.mark.skipif(not HAVE_SPACY, reason="spaCy not installed")
    def test_load_spacy_model_invalid_name(self):
        """Test loading an invalid spaCy model raises OSError."""
        # GIVEN an invalid model name
        model_name = "nonexistent_model_xyz"
        
        # WHEN loading the model
        # THEN it should raise OSError
        with pytest.raises(OSError):
            load_spacy_model(model_name)


class TestBackwardCompatibility:
    """Tests for backward compatibility with old module structure."""
    
    def test_import_from_old_path_cache_utils(self):
        """Test that old cache_utils imports still work (via __init__.py exports)."""
        # WHEN importing from old path via package
        from ipfs_datasets_py.logic.TDFOL.nl import (
            create_cache_cid,
            validate_cid,
            parse_cid,
            MULTIFORMATS_AVAILABLE
        )
        
        # THEN imports should succeed
        assert callable(create_cache_cid)
        assert callable(validate_cid)
        assert callable(parse_cid)
        assert isinstance(MULTIFORMATS_AVAILABLE, bool)
    
    def test_import_from_old_path_spacy_utils(self):
        """Test that old spacy_utils imports still work (via __init__.py exports)."""
        # WHEN importing from old path via package
        from ipfs_datasets_py.logic.TDFOL.nl import (
            require_spacy,
            load_spacy_model,
            HAVE_SPACY
        )
        
        # THEN imports should succeed
        assert callable(require_spacy)
        assert callable(load_spacy_model)
        assert isinstance(HAVE_SPACY, bool)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
