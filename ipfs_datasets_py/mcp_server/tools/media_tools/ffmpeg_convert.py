"""
FFmpeg media conversion MCP tools — thin re-export shim.

Business logic lives in:
    ipfs_datasets_py.processors.multimedia.ffmpeg_convert_engine
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional, Union

from ipfs_datasets_py.processors.multimedia.ffmpeg_convert_engine import (  # noqa: F401
    ffmpeg_convert_media,
    ffmpeg_extract_audio_engine,
    ffmpeg_analyze_media,
    _get_wrapper as get_ffmpeg_wrapper,
)

logger = logging.getLogger(__name__)

# ---- MCP-friendly aliases (match the names the HTM looks up) ----

async def ffmpeg_convert(
    input_file: Union[str, Dict[str, Any]],
    output_file: str,
    output_format: Optional[str] = None,
    video_codec: Optional[str] = None,
    audio_codec: Optional[str] = None,
    video_bitrate: Optional[str] = None,
    audio_bitrate: Optional[str] = None,
    resolution: Optional[str] = None,
    framerate: Optional[str] = None,
    quality: Optional[str] = None,
    preset: Optional[str] = None,
    custom_args: Optional[List[str]] = None,
    timeout: int = 600,
) -> Dict[str, Any]:
    """Convert a media file.  Delegates to ``ffmpeg_convert_media``."""
    return await ffmpeg_convert_media(
        input_file, output_file,
        output_format=output_format, video_codec=video_codec,
        audio_codec=audio_codec, video_bitrate=video_bitrate,
        audio_bitrate=audio_bitrate, resolution=resolution,
        framerate=framerate, quality=quality, preset=preset,
        custom_args=custom_args, timeout=timeout,
    )


async def ffmpeg_extract_audio(
    input_file: Union[str, Dict[str, Any]],
    output_file: str,
    audio_codec: Optional[str] = None,
    audio_bitrate: Optional[str] = None,
    sample_rate: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract audio track.  Delegates to ``ffmpeg_extract_audio_engine``."""
    return await ffmpeg_extract_audio_engine(
        input_file, output_file,
        audio_codec=audio_codec, audio_bitrate=audio_bitrate,
        sample_rate=sample_rate,
    )


async def ffmpeg_analyze(input_file: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Analyse media metadata.  Delegates to ``ffmpeg_analyze_media``."""
    return await ffmpeg_analyze_media(input_file)


# Legacy compat alias
ffmpeg_info = ffmpeg_analyze
