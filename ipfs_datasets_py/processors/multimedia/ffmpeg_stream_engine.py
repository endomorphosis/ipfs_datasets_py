"""
Canonical FFmpeg streaming engine.

Provides ffmpeg_stream_input and ffmpeg_stream_output for media stream
capture and publishing via FFmpeg.

MCP tool wrapper: ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_stream
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .ffmpeg_edit_engine import _parse_time, _validate_output_path, _run_ffmpeg
from .ffmpeg_info_engine import _validate_input_file, ffmpeg_probe

logger = logging.getLogger(__name__)


async def ffmpeg_stream_input(
    stream_url: str,
    output_file: str,
    duration: Optional[str] = None,
    video_codec: str = "copy",
    audio_codec: str = "copy",
    format: Optional[str] = None,
    buffer_size: Optional[str] = None,
    timeout: int = 3600,
) -> Dict[str, Any]:
    """Capture/ingest media from a streaming source using FFmpeg."""
    if not _validate_output_path(output_file):
        return {"status": "error", "error": f"Output path not writable: {output_file}"}

    args: List[str] = []
    if buffer_size:
        args.extend(["-buffer_size", buffer_size])
    if format:
        args.extend(["-f", format])
    args.extend(["-i", stream_url])

    if duration:
        try:
            duration_seconds = _parse_time(duration)
            args.extend(["-t", str(duration_seconds)])
        except (ValueError, IndexError) as exc:
            return {"status": "error", "error": f"Invalid duration format: {exc}"}

    args.extend(["-c:v", video_codec, "-c:a", audio_codec, "-y", output_file])

    logger.info("Starting stream capture: %s -> %s", stream_url, output_file)
    result = await _run_ffmpeg(args, timeout=timeout)
    if result["status"] == "success":
        output_info = await ffmpeg_probe(output_file) if Path(output_file).exists() else None
        return {
            "status": "success",
            "message": "Stream capture completed successfully",
            "stream_url": stream_url,
            "output_file": output_file,
            "output_info": output_info,
            "duration_requested": duration,
            "command": result.get("command", ""),
        }
    return {
        "status": "error",
        "error": "FFmpeg stream capture failed",
        "stream_url": stream_url,
        "ffmpeg_error": result.get("stderr", ""),
        "command": result.get("command", ""),
        "returncode": result.get("returncode", -1),
    }


async def ffmpeg_stream_output(
    input_file: Union[str, Dict[str, Any]],
    stream_url: str,
    video_codec: str = "libx264",
    audio_codec: str = "aac",
    video_bitrate: Optional[str] = None,
    audio_bitrate: Optional[str] = None,
    resolution: Optional[str] = None,
    framerate: Optional[str] = None,
    format: str = "flv",
    preset: str = "fast",
    tune: Optional[str] = None,
    keyframe_interval: Optional[str] = None,
    buffer_size: Optional[str] = None,
    max_muxing_queue_size: str = "1024",
    timeout: int = 3600,
) -> Dict[str, Any]:
    """Stream media to an output destination using FFmpeg."""
    if isinstance(input_file, dict):
        input_path = input_file.get("file_path") or input_file.get("path")
        if not input_path:
            return {"status": "error", "error": "Dataset input must contain 'file_path' or 'path'"}
    else:
        input_path = str(input_file)

    if not _validate_input_file(input_path):
        return {"status": "error", "error": f"Input file not found: {input_path}"}

    info_result = await ffmpeg_probe(input_path)
    if info_result.get("status") != "success":
        return {"status": "error", "error": f"Could not probe input: {info_result.get('error')}"}

    args: List[str] = ["-re", "-i", input_path, "-c:v", video_codec]
    if video_bitrate:
        args.extend(["-b:v", video_bitrate])
    if resolution:
        args.extend(["-s", resolution])
    if framerate:
        args.extend(["-r", framerate])
    if video_codec in ("libx264", "libx265"):
        args.extend(["-preset", preset])
        if tune:
            args.extend(["-tune", tune])
    if keyframe_interval:
        gop = int(float(keyframe_interval) * float(framerate or "30"))
        args.extend(["-g", str(gop)])
    args.extend(["-c:a", audio_codec])
    if audio_bitrate:
        args.extend(["-b:a", audio_bitrate])
    if buffer_size:
        args.extend(["-bufsize", buffer_size])
    args.extend(["-max_muxing_queue_size", max_muxing_queue_size, "-f", format, stream_url])

    logger.info("Starting streaming: %s -> %s", input_path, stream_url)
    result = await _run_ffmpeg(args, timeout=timeout)
    if result["status"] == "success":
        return {
            "status": "success",
            "message": "Streaming completed successfully",
            "input_file": input_path,
            "stream_url": stream_url,
            "command": result.get("command", ""),
        }
    return {
        "status": "error",
        "error": "FFmpeg streaming failed",
        "input_file": input_path,
        "stream_url": stream_url,
        "ffmpeg_error": result.get("stderr", ""),
        "returncode": result.get("returncode", -1),
    }
