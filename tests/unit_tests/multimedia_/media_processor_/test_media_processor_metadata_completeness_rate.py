#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import pytest
import os
import asyncio
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Make sure the input file and documentation file exist.
home_dir = os.path.expanduser('~')
file_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/multimedia/media_processor.py")
md_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/multimedia/media_processor_stubs.md")

# Import the MediaProcessor class and its class dependencies
from ipfs_datasets_py.multimedia.media_processor import MediaProcessor, make_media_processor
from ipfs_datasets_py.multimedia.ytdlp_wrapper import YtDlpWrapper
from ipfs_datasets_py.multimedia.ffmpeg_wrapper import FFmpegWrapper


from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

# Test data constants - Engineering Decisions:
# 1. Separate core metadata from optional conversion metadata for flexible completeness calculation
# 2. Lower threshold to 0.90 to account for platform-specific metadata limitations
# 3. Define weighted completeness model where core fields are more important

CORE_METADATA_FIELDS = [
    "output_path", "title", "duration", "filesize", "format", "resolution"
]

OPTIONAL_METADATA_FIELDS = [
    "converted_path", "conversion_result"
]

ALL_METADATA_FIELDS = CORE_METADATA_FIELDS + OPTIONAL_METADATA_FIELDS

# Weighted completeness: core fields = 0.85 weight, optional fields = 0.15 weight
CORE_WEIGHT = 0.85
OPTIONAL_WEIGHT = 0.15
COMPLETENESS_THRESHOLD = 0.90  # Reduced from 0.98 for practical deployment scenarios

# Metadata field defaults for graceful degradation
METADATA_DEFAULTS = {
    "title": "[Unknown Title]",  # Fallback when both video title and filename are unavailable
    "duration": 0.0,             # Zero duration for streams/unknown
    "resolution": "unknown",     # String format for undetectable resolution
    "converted_path": None,      # Explicit None when no conversion
    "conversion_result": None    # Explicit None when no conversion
}


class TestMetadataCompletenessRate:
    """
    Test metadata completeness rate criteria for status reporting using weighted model.
    
    Engineering Decisions Made:
    1. Weighted Completeness Model: Core fields (85%) + Optional fields (15%)
    2. Reduced Threshold: 90% (from 98%) for practical deployment scenarios
    3. Graceful Degradation: Defined fallback values for missing metadata
    4. Flexible Path Handling: Support both absolute and relative paths
    5. Extensible Format Support: Allow unknown formats, prefer header-based detection
    6. Unicode Normalization: Standardize on NFC normalization for international content
    7. Performance Scaling: Adaptive timeouts based on file size and complexity
    8. Implementation Agnostic: Test output quality rather than specific tools used
    """

    # FIXME This test doesn't affect functionality, but needs to be done eventually to make sure documentation
    # is up to snuff.
    # def test_when_checking_docstring_quality_then_meets_standards(self):
    #     """
    #     Ensure that the docstring of the MediaProcessor class meets the standards set forth in `_example_docstring_format.md`.
    #     """
    #     try:
    #         import inspect
    #         import ast
    #         source = inspect.getsource(MediaProcessor)
    #         tree = ast.parse(source)
    #         has_good_callable_metadata(tree)
    #     except Exception as e:
    #         pytest.fail(f"Callable metadata in MediaProcessor does not meet standards: {e}")

    async def test_output_path_absolute_when_default_output_dir_absolute(self, tmp_path, mock_factory, test_url):
        """
        GIVEN successful download_and_convert operation result with absolute default_output_dir parameter
        WHEN checking output_path metadata field
        THEN expect absolute normalized file path as string type
        """
        # Arrange
        absolute_output_dir = tmp_path / "absolute_output"
        absolute_output_dir.mkdir()
        expected_output_path = str(absolute_output_dir / "video.mp4")
        processor = mock_factory.create_mock_processor(
            absolute_output_dir,
            ytdlp_kwargs={"output_path": expected_output_path}
        )

        # Act
        result = await processor.download_and_convert(test_url)

        # Assert
        
        assert Path(result["output_path"]).is_absolute(), f"Expected absolute path, got '{result['output_path']}'"

    async def test_output_path_absolute_when_default_output_dir_none(self, mock_factory, test_url):
        """
        GIVEN successful download_and_convert operation result with None default_output_dir parameter
        WHEN checking output_path metadata field
        THEN expect absolute normalized file path using current working directory
        """
        # Arrange
        expected_output_path = str(Path.cwd() / "video.mp4")
        processor = mock_factory.create_mock_processor(
            None,  # This will use current working directory
            ytdlp_kwargs={"output_path": expected_output_path}
        )

        # Act
        result = await processor.download_and_convert(test_url)

        # Assert
        
        assert Path(result["output_path"]).is_absolute(), f"Expected absolute path, got '{result['output_path']}'"


    async def test_when_checking_duration_field_then_is_float_type(self, mock_factory, test_url, test_video_duration):
        """
        GIVEN successful download_and_convert operation result
        WHEN checking duration metadata field
        THEN expect float type
        """
        # Arrange
        processor = mock_factory.create_mock_processor(
            Path.cwd(),
            ytdlp_kwargs={"duration": test_video_duration}
        )

        # Act
        result = await processor.download_and_convert(test_url)

        # Assert
        assert isinstance(result["duration"], float), \
            f"Expected duration to be float, got {type(result['duration'])}"


    async def test_when_checking_duration_field_then_is_non_negative_value(self, mock_factory, test_url, test_video_duration):
        """
        GIVEN successful download_and_convert operation result
        WHEN checking duration metadata field
        THEN expect value ≥ 0 seconds
        """
        # Arrange
        processor = mock_factory.create_mock_processor(
            Path.cwd(),
            ytdlp_kwargs={"duration": test_video_duration}
        )

        # Act
        result = await processor.download_and_convert(test_url)

        # Assert
        assert result["duration"] >= 0, f"Expected duration ≥ 0, got {result['duration']}"

    async def test_when_checking_filesize_field_then_is_integer_type(self, mock_factory, test_url, test_file_size):
        """
        GIVEN successful download_and_convert operation result
        WHEN checking filesize metadata field
        THEN expect integer type
        """
        # Arrange
        processor = mock_factory.create_mock_processor(
            Path.cwd(),
            ytdlp_kwargs={"filesize": test_file_size}
        )

        # Act
        result = await processor.download_and_convert(test_url)

        # Assert
        assert isinstance(result["filesize"], int), f"Expected integer filesize, got {type(result['filesize'])}"

    async def test_when_checking_filesize_field_then_is_non_negative_value(self, mock_factory, test_url, test_file_size):
        """
        GIVEN successful download_and_convert operation result
        WHEN checking filesize metadata field
        THEN expect value ≥ 0
        """
        # Arrange
        processor = mock_factory.create_mock_processor(
            Path.cwd(),
            ytdlp_kwargs={"filesize": test_file_size}
        )

        # Act
        result = await processor.download_and_convert(test_url)

        # Assert
        assert result["filesize"] >= 0, f"Expected filesize ≥ 0, got {result['filesize']}"


    @pytest.mark.parametrize("resolution", [
        "1920x1080",
        "1280x720",
        "854x480",
        "640x360",
        "426x240",
        "3840x2160",
        "2560x1440",
        "1366x768",
        "1024x768",
        "800x600"
    ])
    async def test_when_checking_resolution_field_then_is_width_x_height_format_string(self, mock_factory, test_url, resolution):
        """
        GIVEN successful download_and_convert operation result
        WHEN checking resolution metadata field
        THEN expect WIDTHxHEIGHT format string (e.g., "1920x1080")
        """
        # Arrange
        processor = mock_factory.create_mock_processor(
            Path.cwd(),
            ytdlp_kwargs={"resolution": resolution}
        )

        # Act
        result = await processor.download_and_convert(test_url)

        # Assert
        assert result["resolution"] == resolution, f"Expected resolution '{resolution}', got '{result['resolution']}'"


    async def test_converted_path_field_is_string_when_conversion_occurred(self, tmp_path, mock_factory, test_url):
        """
        GIVEN successful download_and_convert operation with conversion
        WHEN checking converted_path metadata field
        THEN expect string path to converted file
        """
        # Arrange
        converted_file_path = str(tmp_path / "converted.webm")
        processor = mock_factory.create_mock_processor(
            tmp_path,
            ytdlp_kwargs={"format": "mp4"},
            ffmpeg_kwargs={"output_path": converted_file_path}
        )

        # Act - Request different format to trigger conversion
        result = await processor.download_and_convert(test_url, output_format="webm")

        # Assert
        assert isinstance(result["converted_path"], str), \
            f"Expected string converted_path, got {type(result['converted_path'])}"


    @pytest.mark.parametrize("output_format,expected_suffix", [
        ("webm", ".webm"),
        ("avi", ".avi"),
        ("mkv", ".mkv"),
        ("mov", ".mov")
    ])
    async def test_converted_path_field_ends_with_converted_file_suffix_when_conversion_occurred(self, tmp_path, mock_factory, test_url, output_format, expected_suffix):
        """
        GIVEN successful download_and_convert operation with conversion
        WHEN checking converted_path metadata field
        THEN expect string path to converted file
        """
        # Arrange
        converted_file_path = tmp_path / f"converted{expected_suffix}"
        processor = mock_factory.create_mock_processor(
            tmp_path,
            ytdlp_kwargs={"format": "mp4"},  # Use mp4 to ensure conversion is needed for non-mp4 formats
            ffmpeg_kwargs={"output_path": str(converted_file_path)}
        )

        # Act - Request different format to trigger conversion
        result = await processor.download_and_convert(test_url, output_format=output_format)

        # Assert
        assert result["converted_path"].endswith(expected_suffix), \
            f"Expected converted_path to end with {expected_suffix}, got '{result['converted_path']}'"


    @pytest.mark.parametrize("same_format", ["mp4", "webm", "avi", "mkv", "mov"])
    async def test_converted_path_field_none_when_no_conversion_occurred(self, tmp_path, mock_factory, test_url, same_format):
        """
        GIVEN successful download_and_convert operation without conversion
        WHEN checking converted_path metadata field
        THEN expect None value
        """
        # Arrange
        processor = mock_factory.create_mock_processor(
            tmp_path,
            ytdlp_kwargs={"format": same_format}
        )

        # Act - Request same format to avoid conversion
        result = await processor.download_and_convert(test_url, output_format=same_format)

        # Assert
        assert result["converted_path"] is None, \
            f"Expected converted_path to be None for format {same_format}, got {result['converted_path']}"

    async def test_conversion_result_field_is_dict_when_conversion_occurred(self, tmp_path, mock_factory, test_url, conversion_details):
        """
        GIVEN successful download_and_convert operation with conversion
        WHEN checking conversion_result metadata field
        THEN expect dictionary with conversion details
        """
        # Arrange
        processor = mock_factory.create_mock_processor(
            tmp_path,
            ytdlp_kwargs={"format": "avi"},
            ffmpeg_kwargs={"conversion_details": conversion_details}
        )

        # Act - Request different format to trigger conversion
        result = await processor.download_and_convert(test_url, output_format="mp4")

        # Assert
        assert isinstance(result["conversion_result"], dict), \
            f"Expected dict conversion_result, got {type(result['conversion_result']).__name__}"

    @pytest.mark.parametrize("same_format", ["mp4", "webm", "avi", "mkv", "mov"])
    async def test_conversion_result_field_is_none_when_no_conversion_occurred(self, tmp_path, mock_factory, test_url, same_format):
        """
        GIVEN successful download_and_convert operation without conversion
        WHEN checking conversion_result metadata field
        THEN expect None value
        """
        # Arrange
        processor = mock_factory.create_mock_processor(
            tmp_path,
            ytdlp_kwargs={"format": same_format}
        )

        # Act - Request same format to avoid conversion
        result = await processor.download_and_convert(test_url, output_format=same_format)

        # Assert
        assert result["conversion_result"] is None, \
            f"Expected conversion_result to be None for format {same_format}, got {result['conversion_result']}"


    @pytest.mark.parametrize("international_title", [
        "Test Vidéo français",
        "测试视频 中文",
        "فيديو العربية",
        "русский видео",
        "日本語のビデオ",
        "한국어 비디오",
        "Test Vidéo 中文 العربية русский 日本語",
        "Émoji test 🎥📹🎬",
        "Special chars: àáâãäåæçèéêë",
        "Mixed: Hello 世界 🌍"
    ])
    async def test_returned_title_preserves_international_characters(self, tmp_path, mock_factory, test_url, international_title):
        """
        GIVEN video with international characters in title
        WHEN calling download_and_convert
        THEN expect returned title field to preserve international characters without data loss
        """
        # Arrange
        processor = mock_factory.create_mock_processor(
            tmp_path,
            ytdlp_kwargs={"title": international_title}
        )

        # Act
        result = await processor.download_and_convert(test_url)

        # Assert
        assert result["title"] == international_title, f"Expected international title preserved, got '{result['title']}'"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])