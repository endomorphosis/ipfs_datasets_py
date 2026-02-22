"""
FFmpeg Convert Engine — canonical business logic for media conversion.

Extracted from ipfs_datasets_py/mcp_server/tools/media_tools/ffmpeg_convert.py.
This module is callable independently of the MCP layer.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

try:
    from ipfs_datasets_py.processors.multimedia import FFmpegWrapper
    _ffmpeg_wrapper: Optional[FFmpegWrapper] = None
    HAVE_FFMPEG_WRAPPER = True
except ImportError:
    HAVE_FFMPEG_WRAPPER = False
    _ffmpeg_wrapper = None


def _get_wrapper() -> Optional[Any]:
    """Lazy-init the global FFmpegWrapper singleton."""
    global _ffmpeg_wrapper
    if not HAVE_FFMPEG_WRAPPER:
        return None
    if _ffmpeg_wrapper is None:
        _ffmpeg_wrapper = FFmpegWrapper(enable_logging=True)  # type: ignore[call-arg]
    return _ffmpeg_wrapper


def _resolve_input_path(input_file: Union[str, Dict[str, Any]]) -> Optional[str]:
    """Normalise *input_file* to a plain string path.

    Accepts either a plain string/Path or a dict with a ``file_path`` / ``path`` key.
    Returns ``None`` when the input cannot be resolved.
    """
    if isinstance(input_file, dict):
        return input_file.get("file_path") or input_file.get("path")
    return str(input_file) if input_file else None


async def ffmpeg_convert_media(
    input_file: Union[str, Dict[str, Any]],
    output_file: str,
    *,
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
    """Convert a media file to a different format.

    Delegates to :class:`~ipfs_datasets_py.processors.multimedia.FFmpegWrapper`.

    Args:
        input_file: Source file path (str or dict with ``file_path``/``path`` key).
        output_file: Destination file path.
        output_format: Target container format (``mp4``, ``webm``, ``mp3``, …).
        video_codec: Video codec override (``libx264``, ``libx265``, …).
        audio_codec: Audio codec override (``aac``, ``libopus``, …).
        video_bitrate: Target video bitrate (``1000k``, ``2M``).
        audio_bitrate: Target audio bitrate (``128k``, ``320k``).
        resolution: Output resolution (``1920x1080``, ``1280x720``).
        framerate: Output frame rate (``30``, ``59.94``).
        quality: Quality preset (``high``, ``medium``, ``low`` or numeric CRF).
        preset: Encoding speed preset (``fast``, ``medium``, ``slow``).
        custom_args: Additional raw ffmpeg arguments.
        timeout: Hard timeout in seconds (default 600).

    Returns:
        Dict with ``success``, ``status``, ``input_file``, ``output_file`` keys.
    """
    input_path = _resolve_input_path(input_file)
    if not input_path:
        return {"success": False, "status": "error", "error": "Invalid or missing input_file",
                "input_file": str(input_file), "output_file": output_file}

    if not output_file:
        return {"success": False, "status": "error", "error": "output_file is required",
                "input_file": input_path, "output_file": output_file}

    wrapper = _get_wrapper()
    if wrapper is None:
        return {"success": False, "status": "error",
                "error": "FFmpegWrapper not available (processors.multimedia not importable)",
                "input_file": input_path, "output_file": output_file}

    if not wrapper.is_available():
        return {"success": False, "status": "error",
                "error": "FFmpeg binary not found — please install FFmpeg",
                "input_file": input_path, "output_file": output_file}

    if not Path(input_path).exists():
        return {"success": False, "status": "error",
                "error": f"Input file not found: {input_path}",
                "input_file": input_path, "output_file": output_file}

    kwargs: Dict[str, Any] = {}
    for k, v in [
        ("output_format", output_format), ("video_codec", video_codec),
        ("audio_codec", audio_codec), ("video_bitrate", video_bitrate),
        ("audio_bitrate", audio_bitrate), ("resolution", resolution),
        ("framerate", framerate), ("quality", quality), ("preset", preset),
        ("custom_args", custom_args), ("timeout", timeout),
    ]:
        if v is not None:
            kwargs[k] = v

    try:
        result = await wrapper.convert_video(input_path=input_path, output_path=output_file, **kwargs)
    except Exception as exc:
        logger.error("ffmpeg_convert_media failed: %s", exc, exc_info=True)
        return {"success": False, "status": "error", "error": str(exc),
                "error_type": type(exc).__name__,
                "input_file": input_path, "output_file": output_file}

    if not isinstance(result, dict):
        result = {"status": "success", "result": result}
    result.setdefault("input_file", input_path)
    result.setdefault("output_file", output_file)
    if "success" in result:
        result["status"] = "success" if result["success"] else "error"
    else:
        result.setdefault("status", "success")
    return result


async def ffmpeg_extract_audio_engine(
    input_file: Union[str, Dict[str, Any]],
    output_file: str,
    *,
    audio_codec: Optional[str] = None,
    audio_bitrate: Optional[str] = None,
    sample_rate: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract audio track from a media file.

    Args:
        input_file: Source file path.
        output_file: Destination audio file path.
        audio_codec: Audio codec (``mp3``, ``aac``, ``flac``).
        audio_bitrate: Bitrate string (``128k``).
        sample_rate: Sample rate (``44100``).

    Returns:
        Dict with ``success`` and ``status`` keys.
    """
    input_path = _resolve_input_path(input_file)
    if not input_path:
        return {"success": False, "status": "error", "error": "Invalid input_file"}

    wrapper = _get_wrapper()
    if wrapper is None:
        return {"success": False, "status": "error", "error": "FFmpegWrapper unavailable"}

    kwargs: Dict[str, Any] = {}
    for k, v in [("audio_codec", audio_codec), ("audio_bitrate", audio_bitrate),
                 ("sample_rate", sample_rate)]:
        if v is not None:
            kwargs[k] = v

    try:
        return await wrapper.extract_audio(input_path=input_path, output_path=output_file, **kwargs)
    except Exception as exc:
        logger.error("ffmpeg_extract_audio_engine failed: %s", exc)
        return {"success": False, "status": "error", "error": str(exc)}


async def ffmpeg_analyze_media(
    input_file: Union[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Analyse a media file and return its metadata.

    Args:
        input_file: Source file path.

    Returns:
        Dict containing stream info, duration, codecs, etc.
    """
    input_path = _resolve_input_path(input_file)
    if not input_path:
        return {"success": False, "status": "error", "error": "Invalid input_file"}

    wrapper = _get_wrapper()
    if wrapper is None:
        return {"success": False, "status": "error", "error": "FFmpegWrapper unavailable"}

    try:
        return await wrapper.analyze_media(input_path=input_path)
    except Exception as exc:
        logger.error("ffmpeg_analyze_media failed: %s", exc)
        return {"success": False, "status": "error", "error": str(exc)}
