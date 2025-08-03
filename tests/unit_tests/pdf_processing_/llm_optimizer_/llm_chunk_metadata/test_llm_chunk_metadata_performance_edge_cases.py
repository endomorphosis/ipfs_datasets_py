#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test suite for performance-related edge cases.

Tests performance characteristics of LLMChunkMetadata operations including
instantiation speed, serialization performance, and memory usage.
"""
import pytest
from pydantic import ValidationError
import time
import psutil
import os
import random

from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunkMetadata
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_factory import (
    LLMChunkMetadataTestDataFactory as DataFactory
)

random.seed(420)  # For reproducibility

class TestLLMChunkMetadataPerformanceEdgeCases:
    """Test suite for performance-related edge cases."""

    def test_instantiation_with_maximum_valid_data_size(self):
        """
        GIVEN all fields at maximum reasonable values
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error within 1 second
        """
        # Constants
        MAX_INSTANTIATION_TIME_SECONDS = 1.0
        CHAR_COUNT = 10_000_000
        WORD_COUNT = 1_500_000
        SENTENCE_COUNT = 50_000
        TOKEN_COUNT = 1_200_000
        LARGE_JSON_TRANSFORMS = '{"x": 0, "y": 0, "width": 9999, "height": 9999, "transforms": [' + \
                               ', '.join(['{"type": "scale", "factor": 1.0}'] * 1000) + ']}'
        
        # Given
        max_data = DataFactory.create_valid_baseline_data()
        max_data.update({
            "character_count": CHAR_COUNT,
            "word_count": WORD_COUNT,
            "sentence_count": SENTENCE_COUNT,
            "token_count": TOKEN_COUNT,
            "original_position": LARGE_JSON_TRANSFORMS
        })
        
        # When
        start_time = time.time()
        metadata = LLMChunkMetadata(**max_data)
        end_time = time.time()
        
        # Then
        instantiation_time = end_time - start_time
        assert instantiation_time < MAX_INSTANTIATION_TIME_SECONDS, \
            f"Instantiation took {instantiation_time:.3f}s, expected < {MAX_INSTANTIATION_TIME_SECONDS}s"

    def test_serialization_performance_with_large_data(self):
        """
        GIVEN LLMChunkMetadata with large field values
        WHEN serialized using .model_dump()
        THEN completion within 1 second without error
        """
        # Constants
        MAX_SERIALIZATION_TIME_SECONDS = 1.0
        CHAR_COUNT = 5_000_000
        WORD_COUNT = 750_000
        LARGE_JSON_DATA = '{"data": "' + 'x' * 10_000 + '"}'  # Large JSON string
        
        # Given
        large_data = DataFactory.create_valid_baseline_data()
        large_data.update({
            "character_count": CHAR_COUNT,
            "word_count": WORD_COUNT,
            "original_position": LARGE_JSON_DATA
        })
        metadata = LLMChunkMetadata(**large_data)
        
        # When
        start_time = time.time()
        serialized = metadata.model_dump()
        end_time = time.time()
        
        # Then
        serialization_time = end_time - start_time
        assert serialization_time < MAX_SERIALIZATION_TIME_SECONDS, \
            f"Serialization took {serialization_time:.3f}s, expected < {MAX_SERIALIZATION_TIME_SECONDS}s"

    def test_equality_comparison_performance(self):
        """
        GIVEN two LLMChunkMetadata instances with large field values
        WHEN performing equality comparison
        THEN comparison within 1 second without error
        """
        # Constants
        MAX_COMPARISON_TIME_SECONDS = 1.0
        CHAR_COUNT = 3_000_000
        POSITION_ARRAY_SIZE = 1000
        LARGE_POSITION_JSON = '{"positions": [' + ','.join([f'{{"x": {i}, "y": {i}}}' for i in range(POSITION_ARRAY_SIZE)]) + ']}'
        EXPECTED_RESULT = True
        
        # Given
        large_data = DataFactory.create_valid_baseline_data()
        large_data.update({
            "CHAR_COUNT": CHAR_COUNT,
            "original_position": LARGE_POSITION_JSON
        })
        metadata1 = LLMChunkMetadata(**large_data)
        metadata2 = LLMChunkMetadata(**large_data)
        
        # When
        start_time = time.time()
        result = metadata1 == metadata2
        end_time = time.time()
        
        # Then
        assert result is EXPECTED_RESULT
        comparison_time = end_time - start_time
        assert comparison_time < MAX_COMPARISON_TIME_SECONDS, \
            f"Comparison took {comparison_time:.3f}s, expected < {MAX_COMPARISON_TIME_SECONDS}s"

    def test_hash_generation_consistency_under_load(self):
        """
        GIVEN multiple LLMChunkMetadata instances with varying data sizes
        WHEN generating hash values repeatedly
        THEN hash generated per chunk is under 1 second without error.
        """
        # Constants
        MAX_HASH_TIME_SECONDS = 1.0
        INSTANCE_COUNT = 100
        AVG_PARAGRAPH_LEN = 5 #sentences
        AVG_LEN_ENGLISH_SENTENCE = 15 # words
        AVG_CHARS_IN_WORD = 5 # TODO Confirm this.

        SENTENCE_COUNT = AVG_PARAGRAPH_LEN + random.randint(-4, 5)
        WORD_COUNT = round(SENTENCE_COUNT * (AVG_LEN_ENGLISH_SENTENCE + random.randint(-14, 10)))
        CHAR_COUNT = round(WORD_COUNT * (AVG_CHARS_IN_WORD + random.randint(-2, 10)))

        MAX_CHAR_LEN = 240

        # Given
        instances = []
        for idx in range(INSTANCE_COUNT):
            data = DataFactory.create_valid_baseline_data()
            data.update({
                "word_count": WORD_COUNT,
                "sentence_count": SENTENCE_COUNT,
                "CHAR_COUNT": CHAR_COUNT,
                "element_id": f"element_{idx}_{'x' * MAX_CHAR_LEN}"
            })
            instances.append(LLMChunkMetadata(**data))

        # When
        start_time = time.time()
        hashes = [hash(instance) for instance in instances]
        end_time = time.time()
        
        # Then
        assert len(hashes) == INSTANCE_COUNT
        total_hash_time = end_time - start_time
        per_instance_time = total_hash_time / len(instances)
        assert per_instance_time < MAX_HASH_TIME_SECONDS, \
            f"Hash generation took {per_instance_time:.3f}s per instance, expected < {MAX_HASH_TIME_SECONDS}s"

    def test_hash_generation_hashes_and_instances_are_unique(self):
        """
        GIVEN multiple LLMChunkMetadata instances
        WHEN generating hash values
        THEN all hashes are unique.
        """
        # Constants
        INSTANCE_COUNT = 30
        
        # Given
        instances = []
        for i in range(INSTANCE_COUNT):
            data = DataFactory.create_valid_baseline_data()
            data["element_id"] = f"element_{i}"
            instances.append(LLMChunkMetadata(**data))
        
        # When
        hashes = [hash(instance) for instance in instances]
        
        # Then
        assert len(hashes) == len(set(hashes)), "Hashes are not unique across instances"


    def test_memory_usage_with_multiple_instances(self):
        """
        GIVEN creation of 10,000 LLMChunkMetadata instances
        WHEN monitoring memory usage
        THEN memory consumption is under 100MB.
        """
        # Constants
        MAX_MEMORY_USAGE_MB = 100.0
        PERFORMANCE_TEST_INSTANCES = 10_000

        # Constants
        MAX_CHAR_LEN = 240
        AVG_PARAGRAPH_LEN = 5 #sentences
        AVG_LEN_ENGLISH_SENTENCE = 15 # words
        AVG_CHARS_IN_WORD = 5 # TODO Confirm this.

        SENTENCE_COUNT = AVG_PARAGRAPH_LEN + random.randint(-4, 5)
        WORD_COUNT = round(SENTENCE_COUNT * (AVG_LEN_ENGLISH_SENTENCE + random.randint(-14, 10)))
        CHAR_COUNT = round(WORD_COUNT * (AVG_CHARS_IN_WORD + random.randint(-2, 10)))

        # Given
        process = psutil.Process(os.getpid())
        baseline_memory = process.memory_info().rss / 1024 / 1024  # Convert to MB

        # When
        instances = []
        try:
            for idx in range(PERFORMANCE_TEST_INSTANCES):
                data = DataFactory.create_valid_baseline_data()
                data.update({
                    "word_count": WORD_COUNT,
                    "sentence_count": SENTENCE_COUNT,
                    "CHAR_COUNT": CHAR_COUNT,
                    "element_id": f"element_{idx}_{'x' * MAX_CHAR_LEN}"
                })
                instances.append(LLMChunkMetadata(**data))
            
            peak_memory = process.memory_info().rss / 1024 / 1024  # Convert to MB
            memory_increase = peak_memory - baseline_memory
            
            # Then
            assert memory_increase < MAX_MEMORY_USAGE_MB, \
                f"Memory usage increased by {memory_increase:.2f}MB, expected < {MAX_MEMORY_USAGE_MB}MB"
        finally:
            # Clean up to avoid memory issues in subsequent tests
            del instances

if __name__ == "__main__":
    pytest.main([__file__, "-v"])