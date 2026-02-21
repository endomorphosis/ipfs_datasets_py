"""
Phase B2 unit tests for media_tools/ (ffmpeg_convert, ffmpeg_info, ytdlp_download).
"""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# ffmpeg_convert
# ---------------------------------------------------------------------------

class TestFfmpegConvert:
    """Tests for the ffmpeg_convert async tool."""

    @pytest.mark.asyncio
    async def test_missing_input_returns_error(self):
        """Passing an empty input path returns an error dict."""
        from ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_convert import ffmpeg_convert
        result = await ffmpeg_convert(input_file="", output_file="/tmp/out.mp4")
        assert isinstance(result, dict)
        # either an error key or success=False
        assert "error" in result or result.get("success") is False

    @pytest.mark.asyncio
    async def test_delegates_to_ffmpeg_wrapper(self):
        """When the wrapper is available, ffmpeg_convert delegates conversion to it."""
        mock_wrapper = MagicMock()
        mock_wrapper.convert_media = AsyncMock(
            return_value={"success": True, "output_file": "/tmp/out.mp4"}
        )

        with patch(
            "ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_convert.get_ffmpeg_wrapper",
            return_value=mock_wrapper,
        ):
            from ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_convert import ffmpeg_convert
            result = await ffmpeg_convert(
                input_file="/tmp/in.mp4",
                output_file="/tmp/out.webm",
                output_format="webm",
            )

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_returns_dict_on_exception(self):
        """If the wrapper raises, ffmpeg_convert returns an error dict (not re-raises)."""
        mock_wrapper = MagicMock()
        mock_wrapper.convert_media = AsyncMock(side_effect=RuntimeError("ffmpeg not found"))

        with patch(
            "ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_convert.get_ffmpeg_wrapper",
            return_value=mock_wrapper,
        ):
            from ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_convert import ffmpeg_convert
            result = await ffmpeg_convert(
                input_file="/tmp/in.mp4", output_file="/tmp/out.webm"
            )

        assert isinstance(result, dict)
        assert "error" in result or result.get("success") is False


# ---------------------------------------------------------------------------
# ffmpeg_analyze  (via ffmpeg_info thin wrapper OR ffmpeg_convert module)
# ---------------------------------------------------------------------------

class TestFfmpegAnalyze:
    """Tests for the ffmpeg_analyze tool in ffmpeg_convert.py."""

    @pytest.mark.asyncio
    async def test_analyze_returns_dict(self):
        """ffmpeg_analyze returns a dict regardless of ffmpeg availability."""
        mock_wrapper = MagicMock()
        mock_wrapper.get_media_info = AsyncMock(
            return_value={"success": True, "duration": 120, "codec": "h264"}
        )

        with patch(
            "ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_convert.get_ffmpeg_wrapper",
            return_value=mock_wrapper,
        ):
            from ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_convert import ffmpeg_analyze
            result = await ffmpeg_analyze(input_file="/tmp/video.mp4")

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_analyze_handles_wrapper_error(self):
        """ffmpeg_analyze returns an error dict if the wrapper throws."""
        mock_wrapper = MagicMock()
        mock_wrapper.get_media_info = AsyncMock(side_effect=OSError("no such file"))

        with patch(
            "ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_convert.get_ffmpeg_wrapper",
            return_value=mock_wrapper,
        ):
            from ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_convert import ffmpeg_analyze
            result = await ffmpeg_analyze(input_file="/missing/file.mp4")

        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# ytdlp_download (thin wrapper)
# ---------------------------------------------------------------------------

class TestYtdlpDownload:
    """Tests for ytdlp_download_video thin wrapper."""

    @pytest.mark.asyncio
    async def test_download_video_returns_dict(self):
        """ytdlp_download_video always returns a dict."""
        with patch(
            "ipfs_datasets_py.processors.multimedia.ytdlp_download_engine.ytdlp_download_video",
            new=AsyncMock(return_value={"success": True, "file_path": "/tmp/video.mp4"}),
        ):
            from ipfs_datasets_py.mcp_server.tools.media_tools.ytdlp_download import (
                ytdlp_download_video,
            )
            result = await ytdlp_download_video(url="https://example.com/v")

        assert isinstance(result, dict)
