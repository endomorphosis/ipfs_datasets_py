"""Tests for OntologyCritic shared cache persistence methods.

This module tests the save_shared_cache() and load_shared_cache() methods that  
allow the class-level evaluation cache to persist across Python process restarts.
"""

import json
import os
import tempfile
import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_critic import (
    OntologyCritic,
    CriticScore,
)
from ipfs_datasets_py.optimizers.common.path_validator import PathValidationError


class TestOntologyCriticCachePersistence:
    """Tests for shared cache save/load functionality."""

    def setup_method(self):
        """Clear the shared cache before each test."""
        OntologyCritic.clear_shared_cache()

    def teardown_method(self):
        """Clear the shared cache after each test."""
        OntologyCritic.clear_shared_cache()

    def test_save_empty_cache(self):
        """Test saving an empty cache."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            filepath = f.name

        try:
            OntologyCritic.save_shared_cache(filepath)

            # Verify file was created and contains empty object
            assert os.path.exists(filepath)
            with open(filepath, 'r') as f:
                data = json.load(f)
            assert data == {}
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)

    def test_save_and_load_single_entry(self):
        """Test round-trip of a single cache entry."""
        # Populate cache with one entry
        score = CriticScore(
            completeness=0.8,
            consistency=0.9,
            clarity=0.75,
            granularity=0.85,
            relationship_coherence=0.80,
            domain_alignment=0.88,
        )
        cache_key = "test_key_123"
        OntologyCritic._SHARED_EVAL_CACHE[cache_key] = score

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            filepath = f.name

        try:
            # Save
            OntologyCritic.save_shared_cache(filepath)
            
            # Clear cache
            OntologyCritic.clear_shared_cache()
            assert OntologyCritic.shared_cache_size() == 0

            # Load
            count = OntologyCritic.load_shared_cache(filepath)
            assert count == 1
            assert OntologyCritic.shared_cache_size() == 1

            # Verify data integrity
            loaded_score = OntologyCritic._SHARED_EVAL_CACHE[cache_key]
            assert loaded_score.completeness == score.completeness
            assert loaded_score.consistency == score.consistency
            assert loaded_score.clarity == score.clarity
            assert loaded_score.granularity == score.granularity
            assert loaded_score.relationship_coherence == score.relationship_coherence
            assert loaded_score.domain_alignment == score.domain_alignment
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)

    def test_save_and_load_multiple_entries(self):
        """Test round-trip of multiple cache entries."""
        # Populate cache with multiple entries
        for i in range(10):
            score = CriticScore(
                completeness=0.5 + i * 0.05,
                consistency=0.6 + i * 0.04,
                clarity=0.7 + i * 0.03,
                granularity=0.65 + i * 0.035,
                relationship_coherence=0.55 + i * 0.045,
                domain_alignment=0.75 + i * 0.025,
            )
            OntologyCritic._SHARED_EVAL_CACHE[f"key_{i}"] = score

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            filepath = f.name

        try:
            # Save
            OntologyCritic.save_shared_cache(filepath)
            
            # Clear and reload
            original_keys = set(OntologyCritic._SHARED_EVAL_CACHE.keys())
            OntologyCritic.clear_shared_cache()
            
            count = OntologyCritic.load_shared_cache(filepath)
            assert count == 10
            assert OntologyCritic.shared_cache_size() == 10

            # Verify all keys are present
            loaded_keys = set(OntologyCritic._SHARED_EVAL_CACHE.keys())
            assert loaded_keys == original_keys
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)

    def test_load_merge_mode(self):
        """Test loading cache in merge mode preserves existing entries."""
        # Start with some entries
        score1 = CriticScore(
            completeness=0.8, consistency=0.8, clarity=0.8,
            granularity=0.8, relationship_coherence=0.8, domain_alignment=0.8
        )
        OntologyCritic._SHARED_EVAL_CACHE["existing_key"] = score1

        # Create a cache file with different entries
        score2 = CriticScore(
            completeness=0.9, consistency=0.9, clarity=0.9,
            granularity=0.9, relationship_coherence=0.9, domain_alignment=0.9
        )
        saved_cache = {"new_key": score2.to_dict()}

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            filepath = f.name
            json.dump(saved_cache, f)

        try:
            # Load with merge=True
            count = OntologyCritic.load_shared_cache(filepath, merge=True)
            assert count == 1
            assert OntologyCritic.shared_cache_size() == 2

            # Both keys should be present
            assert "existing_key" in OntologyCritic._SHARED_EVAL_CACHE
            assert "new_key" in OntologyCritic._SHARED_EVAL_CACHE
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)

    def test_load_without_merge_clears_cache(self):
        """Test loading cache without merge clears existing entries."""
        # Start with some entries
        score1 = CriticScore(
            completeness=0.8, consistency=0.8, clarity=0.8,
            granularity=0.8, relationship_coherence=0.8, domain_alignment=0.8
        )
        OntologyCritic._SHARED_EVAL_CACHE["existing_key"] = score1

        # Create a cache file with different entries
        score2 = CriticScore(
            completeness=0.9, consistency=0.9, clarity=0.9,
            granularity=0.9, relationship_coherence=0.9, domain_alignment=0.9
        )
        saved_cache = {"new_key": score2.to_dict()}

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            filepath = f.name
            json.dump(saved_cache, f)

        try:
            # Load with merge=False (default)
            count = OntologyCritic.load_shared_cache(filepath, merge=False)
            assert count == 1
            assert OntologyCritic.shared_cache_size() == 1

            # Only new key should be present
            assert "existing_key" not in OntologyCritic._SHARED_EVAL_CACHE
            assert "new_key" in OntologyCritic._SHARED_EVAL_CACHE
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)

    def test_load_nonexistent_file(self):
        """Test loading from nonexistent file raises path/file-not-found error."""
        with pytest.raises((FileNotFoundError, PathValidationError)):
            OntologyCritic.load_shared_cache("/nonexistent/path/cache.json")

    def test_load_invalid_json(self):
        """Test loading invalid JSON raises JSONDecodeError."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            filepath = f.name
            f.write("invalid json {{{")

        try:
            with pytest.raises(json.JSONDecodeError):
                OntologyCritic.load_shared_cache(filepath)
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)

    def test_load_invalid_format(self):
        """Test loading non-dict JSON raises ValueError."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            filepath = f.name
            json.dump(["array", "not", "dict"], f)

        try:
            with pytest.raises(ValueError, match="must contain a JSON object"):
                OntologyCritic.load_shared_cache(filepath)
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)

    def test_save_creates_directory(self):
        """Test that save_shared_cache creates parent directories if needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "nested", "dir", "cache.json")
            
            # Directory doesn't exist yet
            assert not os.path.exists(os.path.dirname(filepath))

            # Should create it
            OntologyCritic.save_shared_cache(filepath)
            assert os.path.exists(filepath)

    def test_cache_with_metadata(self):
        """Test round-trip of cache entry with metadata."""
        score = CriticScore(
            completeness=0.8,
            consistency=0.9,
            clarity=0.75,
            granularity=0.85,
            relationship_coherence=0.80,
            domain_alignment=0.88,
            metadata={"domain": "legal", "timestamp": "2024-01-01"}
        )
        OntologyCritic._SHARED_EVAL_CACHE["with_metadata"] = score

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            filepath = f.name

        try:
            OntologyCritic.save_shared_cache(filepath)
            OntologyCritic.clear_shared_cache()
            OntologyCritic.load_shared_cache(filepath)

            loaded = OntologyCritic._SHARED_EVAL_CACHE["with_metadata"]
            assert loaded.metadata == {"domain": "legal", "timestamp": "2024-01-01"}
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)

    def test_cache_with_feedback_lists(self):
        """Test round-trip of cache entry with strengths/weaknesses/recommendations."""
        score = CriticScore(
            completeness=0.8,
            consistency=0.9,
            clarity=0.75,
            granularity=0.85,
            relationship_coherence=0.80,
            domain_alignment=0.88,
            strengths=["Well structured", "Clear relationships"],
            weaknesses=["Missing some entities"],
            recommendations=["Add more entity types", "Improve coverage"]
        )
        OntologyCritic._SHARED_EVAL_CACHE["with_feedback"] = score

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            filepath = f.name

        try:
            OntologyCritic.save_shared_cache(filepath)
            OntologyCritic.clear_shared_cache()
            OntologyCritic.load_shared_cache(filepath)

            loaded = OntologyCritic._SHARED_EVAL_CACHE["with_feedback"]
            assert loaded.strengths == ["Well structured", "Clear relationships"]
            assert loaded.weaknesses == ["Missing some entities"]
            assert loaded.recommendations == ["Add more entity types", "Improve coverage"]
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)

    def test_load_skips_invalid_entries(self):
        """Test that loading skips invalid cache entries but continues."""
        # Create cache file with mix of valid and invalid entries
        valid_score = CriticScore(
            completeness=0.8, consistency=0.9, clarity=0.75,
            granularity=0.85, relationship_coherence=0.80, domain_alignment=0.88
        )
        cache_data = {
            "valid_key": valid_score.to_dict(),
            "invalid_key": "not_a_dict",  # String instead of dict - will fail
            "another_valid": valid_score.to_dict()
        }

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            filepath = f.name
            json.dump(cache_data, f)

        try:
            # Should load 2 valid entries, skip 1 invalid
            count = OntologyCritic.load_shared_cache(filepath)
            assert count == 2
            assert "valid_key" in OntologyCritic._SHARED_EVAL_CACHE
            assert "another_valid" in OntologyCritic._SHARED_EVAL_CACHE
            assert "invalid_key" not in OntologyCritic._SHARED_EVAL_CACHE
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)

    def test_large_cache_roundtrip(self):
        """Test round-trip with cache at max size."""
        # Fill cache to max size
        for i in range(256):  # _SHARED_EVAL_CACHE_MAX
            score = CriticScore(
                completeness=0.5 + (i % 50) * 0.01,
                consistency=0.6 + (i % 40) * 0.01,
                clarity=0.7 + (i % 30) * 0.01,
                granularity=0.65 + (i % 35) * 0.01,
                relationship_coherence=0.55 + (i % 45) * 0.01,
                domain_alignment=0.75 + (i % 25) * 0.01,
            )
            OntologyCritic._SHARED_EVAL_CACHE[f"entry_{i}"] = score

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            filepath = f.name

        try:
            OntologyCritic.save_shared_cache(filepath)
            OntologyCritic.clear_shared_cache()
            
            count = OntologyCritic.load_shared_cache(filepath)
            assert count == 256
            assert OntologyCritic.shared_cache_size() == 256
        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)
