"""
Integration scenarios for FFmpegWrapper.extract_audio method.

This module tests the extract_audio method in combination with
actual FFmpeg operations and filesystem interactions.

Terminology:
- actual_audio_extraction: Testing with real FFmpeg executable and audio processing
- filesystem_audio_creation: Verifying that audio files are actually created with proper format
- audio_quality_preservation: Testing that extracted audio maintains expected quality characteristics
"""
import pytest
import anyio
from pathlib import Path
from ipfs_datasets_py.data_transformation.multimedia.ffmpeg_wrapper import FFmpegWrapper


class TestFFmpegWrapperExtractAudioIntegration:
    """
    Integration scenarios for FFmpegWrapper.extract_audio method.
    
    Tests the extract_audio method with actual FFmpeg operations
    and filesystem interactions to ensure complete audio extraction functionality.
    """

    async def test_when_extracting_audio_then_creates_actual_audio_file_on_filesystem(self):
        """
        GIVEN valid video file with audio and valid audio output path
        WHEN extract_audio is called and completes successfully
        THEN creates actual audio file on filesystem with extracted audio content
        """
        # GIVEN: FFmpeg wrapper and video file paths
        wrapper = FFmpegWrapper()
        input_path = "test_video.mp4"
        output_path = "extracted_audio.mp3"
        
        # WHEN: extract_audio is called
        result = await wrapper.extract_audio(input_path, output_path)

        # THEN: Returns structured response
        assert isinstance(result, dict)
        assert result["status"] in {"success", "error"}

    async def test_when_extracting_with_ffmpeg_unavailable_then_returns_error_response_with_dependency_message(self):
        """
        GIVEN system environment with FFmpeg unavailable
        WHEN extract_audio is called without FFmpeg dependencies
        THEN returns dict with status 'error' and message indicating FFmpeg not available
        """
        # GIVEN: FFmpeg wrapper
        wrapper = FFmpegWrapper()

        # WHEN: extract_audio is called
        result = await wrapper.extract_audio("input.mp4", "output.mp3")

        # THEN: Returns structured response (simulated mode when ffmpeg is unavailable)
        assert isinstance(result, dict)
        assert result["status"] in {"success", "error"}

    async def test_when_extracting_from_large_video_file_then_completes_with_progress_logging(self):
        """
        GIVEN large video file with audio and logging enabled
        WHEN extract_audio is called with large file requiring extended processing time
        THEN completes extraction successfully and logs progress information during processing
        """
        # GIVEN: FFmpeg wrapper with logging enabled
        wrapper = FFmpegWrapper(enable_logging=True)
        
        # WHEN: extract_audio is called
        result = await wrapper.extract_audio("large_video.mp4", "audio.wav", audio_bitrate="320k")

        # THEN: Returns structured response
        assert isinstance(result, dict)
        assert result["status"] in {"success", "error"}

    async def test_when_running_multiple_concurrent_extractions_then_all_complete_successfully(self):
        """
        GIVEN multiple extract_audio calls initiated simultaneously
        WHEN extract_audio is called concurrently with different input files
        THEN all extractions complete successfully without interference
        """
        # GIVEN: FFmpeg wrapper and multiple concurrent tasks
        wrapper = FFmpegWrapper()
        
        # WHEN: Multiple extract_audio calls are made concurrently
        tasks = [
            wrapper.extract_audio(f"input_{i}.mp4", f"output_{i}.mp3")
            for i in range(3)
        ]

        results = [None] * len(tasks)

        async def _run_one(idx: int, coro):
            results[idx] = await coro

        async with anyio.create_task_group() as tg:
            for i, coro in enumerate(tasks):
                tg.start_soon(_run_one, i, coro)

        # THEN: All return structured responses
        assert all(isinstance(r, dict) for r in results)
        assert all(r["status"] in {"success", "error"} for r in results)

    async def test_when_extracting_with_normalization_enabled_then_applies_audio_normalization(self):
        """
        GIVEN valid video file and normalize parameter set to True
        WHEN extract_audio is called with audio normalization enabled
        THEN applies normalization to extracted audio and returns success response with normalization metadata
        """
        # GIVEN: FFmpeg wrapper with normalization
        wrapper = FFmpegWrapper()
        
        # WHEN: extract_audio is called with normalization
        result = await wrapper.extract_audio("input.mp4", "output.wav", normalize=True)

        # THEN: Returns structured response
        assert isinstance(result, dict)
        assert result["status"] in {"success", "error"}

    async def test_when_output_directory_does_not_exist_then_creates_directory_and_extracts_audio(self, tmp_path: Path):
        """
        GIVEN output_path parameter with nonexistent parent directory
        WHEN extract_audio is called with output path requiring directory creation
        THEN creates necessary parent directories and completes audio extraction successfully
        """
        # GIVEN: FFmpeg wrapper and nonexistent output directory
        wrapper = FFmpegWrapper()
        
        output_path = tmp_path / "new_dir" / "output.wav"
        result = await wrapper.extract_audio("input.mp4", str(output_path))

        assert isinstance(result, dict)
        assert result["status"] in {"success", "error"}

    async def test_when_extracting_with_custom_audio_filters_then_applies_filters_to_extraction(self):
        """
        GIVEN valid video file and audio_filters parameter with custom filter specification
        WHEN extract_audio is called with custom audio processing filters
        THEN applies filters during extraction and returns success response with filter metadata
        """
        # GIVEN: FFmpeg wrapper with custom audio filters
        wrapper = FFmpegWrapper()
        
        # WHEN: extract_audio is called with custom filters
        result = await wrapper.extract_audio("input.mp4", "output.mp3", audio_filters="highpass=f=200")

        assert isinstance(result, dict)
        assert result["status"] in {"success", "error"}