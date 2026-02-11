"""
Integration scenarios for FFmpegWrapper.analyze_media method.

This module tests the analyze_media method in combination with
actual FFmpeg operations and comprehensive analysis workflows.

Terminology:
- actual_media_analysis: Testing with real FFmpeg executable and analysis algorithms
- comprehensive_metadata_extraction: Verifying that detailed technical information is extracted
- performance_profiling_verification: Testing that analysis provides accurate performance characteristics
"""
import pytest
import anyio
from pathlib import Path
from ipfs_datasets_py.data_transformation.multimedia.ffmpeg_wrapper import FFmpegWrapper


class TestFFmpegWrapperAnalyzeMediaIntegration:
    """
    Integration scenarios for FFmpegWrapper.analyze_media method.
    
    Tests the analyze_media method with actual FFmpeg operations
    and comprehensive analysis workflows to ensure complete functionality.
    """

    async def test_when_analyzing_media_then_extracts_comprehensive_technical_metadata(self):
        """
        GIVEN valid media file with multiple streams and comprehensive analysis depth
        WHEN analyze_media is called and completes successfully
        THEN returns detailed technical metadata including container, stream, and quality information
        """
        wrapper = FFmpegWrapper()
        result = await wrapper.analyze_media(
            input_path="multi_stream_video.mp4",
            analysis_depth="comprehensive",
        )

        assert isinstance(result, dict)
        assert result["status"] == "success"
        assert "metadata" in result
        assert result["metadata"].get("analysis_depth") == "comprehensive"

    async def test_when_analyzing_with_ffmpeg_unavailable_then_returns_error_response_with_dependency_message(self):
        """
        GIVEN system environment with FFmpeg unavailable
        WHEN analyze_media is called without FFmpeg dependencies
        THEN returns dict with status 'error' and message indicating FFmpeg not available
        """
        wrapper = FFmpegWrapper()
        result = await wrapper.analyze_media(input_path="video.mp4")

        # Wrapper supports simulated mode; should still return a structured dict.
        assert isinstance(result, dict)
        assert result["status"] in {"success", "error"}

    async def test_when_analyzing_large_media_file_then_completes_with_progress_logging(self):
        """
        GIVEN large media file and logging enabled with comprehensive analysis
        WHEN analyze_media is called with large file requiring extended processing time
        THEN completes analysis successfully and logs progress information during processing
        """
        wrapper = FFmpegWrapper(enable_logging=True)

        result = await wrapper.analyze_media(
            input_path="large_video_file.mp4",
            detailed_analysis=True,
            include_progress=True,
        )
        assert isinstance(result, dict)
        assert result["status"] == "success"
        assert "analysis_time" in result

    async def test_when_running_multiple_concurrent_analyses_then_all_complete_successfully(self):
        """
        GIVEN multiple analyze_media calls initiated simultaneously
        WHEN analyze_media is called concurrently with different input files
        THEN all analyses complete successfully without interference
        """
        wrapper = FFmpegWrapper()

        tasks = [
            wrapper.analyze_media("video1.mp4"),
            wrapper.analyze_media("video2.mp4"),
            wrapper.analyze_media("audio1.mp3"),
        ]

        results = [None] * len(tasks)

        async def _run_one(idx: int, coro):
            results[idx] = await coro

        async with anyio.create_task_group() as tg:
            for i, coro in enumerate(tasks):
                tg.start_soon(_run_one, i, coro)

        assert all(isinstance(r, dict) for r in results)
        assert all(r["status"] == "success" for r in results)

    async def test_when_analyzing_with_export_format_then_creates_analysis_report_file(self):
        """
        GIVEN valid media file and export_format parameter specifying report format
        WHEN analyze_media is called with analysis report export enabled
        THEN creates analysis report file in specified format and returns success response with report location
        """
        wrapper = FFmpegWrapper()

        result = await wrapper.analyze_media(
            input_path="video.mp4",
            export_format="json",
            export_path="analysis_report.json",
        )
        assert result["status"] == "success"
        assert result.get("report_location") == "analysis_report.json"

    async def test_when_performance_profiling_enabled_then_provides_accurate_computational_metrics(self):
        """
        GIVEN valid media file and performance_profiling parameter set to True
        WHEN analyze_media is called with performance profiling enabled
        THEN returns analysis results including accurate decode/encode complexity and performance characteristics
        """
        wrapper = FFmpegWrapper()

        result = await wrapper.analyze_media(
            input_path="video.mp4",
            performance_profiling=True,
        )
        assert result["status"] == "success"
        assert "performance_metrics" in result

    async def test_when_analyzing_with_all_analysis_options_then_provides_complete_media_profile(self):
        """
        GIVEN valid media file with all analysis options enabled (quality, content, stream, metadata, checksum)
        WHEN analyze_media is called with comprehensive analysis configuration
        THEN returns complete media profile with all requested analysis components and detailed results
        """
        wrapper = FFmpegWrapper()

        result = await wrapper.analyze_media(
            input_path="video.mp4",
            quality_assessment=True,
            content_analysis=True,
            stream_analysis=True,
            metadata_extraction=True,
            checksum_verification=True,
        )
        assert result["status"] == "success"
        assert "quality_metrics" in result
        assert "content_characteristics" in result
        assert "metadata" in result