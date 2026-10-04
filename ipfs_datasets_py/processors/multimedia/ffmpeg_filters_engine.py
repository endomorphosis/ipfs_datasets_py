"""
Canonical FFmpeg filters engine.

Provides ffmpeg_apply_filters and get_available_filters for audio/video
filter application.

MCP tool wrapper: ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_filters
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import anyio

from .ffmpeg_edit_engine import _validate_output_path, _run_ffmpeg
from .ffmpeg_info_engine import _validate_input_file

logger = logging.getLogger(__name__)


async def ffmpeg_apply_filters(
    input_file: Union[str, Dict[str, Any]],
    output_file: str,
    video_filters: Optional[List[str]] = None,
    audio_filters: Optional[List[str]] = None,
    filter_complex: Optional[str] = None,
    output_format: Optional[str] = None,
    preserve_metadata: bool = True,
    timeout: int = 600,
) -> Dict[str, Any]:
    """Apply video and audio filters to a media file using FFmpeg."""
    if isinstance(input_file, dict):
        input_path = input_file.get("file_path") or input_file.get("path")
        if not input_path:
            return {"status": "error", "error": "Dataset input must contain 'file_path' or 'path'"}
    else:
        input_path = str(input_file)

    if not _validate_input_file(input_path):
        return {"status": "error", "error": f"Input file not found or not accessible: {input_path}"}
    if not _validate_output_path(output_file):
        return {"status": "error", "error": f"Output path not writable: {output_file}"}

    input_size = Path(input_path).stat().st_size
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"

    cmd: List[str] = ["-i", input_path]
    filters_applied: List[str] = []

    if filter_complex:
        cmd.extend(["-filter_complex", filter_complex])
        filters_applied.append(f"complex: {filter_complex}")
    else:
        if video_filters:
            cmd.extend(["-vf", ",".join(video_filters)])
            filters_applied.extend(f"video: {vf}" for vf in video_filters)
        if audio_filters:
            cmd.extend(["-af", ",".join(audio_filters)])
            filters_applied.extend(f"audio: {af}" for af in audio_filters)

    if output_format:
        cmd.extend(["-f", output_format])
    if preserve_metadata:
        cmd.extend(["-map_metadata", "0"])
    cmd.append(output_file)

    logger.info("Applying filters: %s", " ".join([ffmpeg_bin] + cmd))
    result = await _run_ffmpeg(cmd, timeout=timeout)

    if result.get("returncode", result.get("status")) in (0, "success"):
        output_size = Path(output_file).stat().st_size if Path(output_file).exists() else 0
        return {
            "status": "success",
            "input_file": input_path,
            "output_file": output_file,
            "filters_applied": filters_applied,
            "file_size_before": input_size,
            "file_size_after": output_size,
            "compression_ratio": (input_size - output_size) / input_size if input_size > 0 else 0,
            "message": f"Successfully applied {len(filters_applied)} filters",
        }
    return {
        "status": "error",
        "error": "FFmpeg filter application failed",
        "input_file": input_path,
        "output_file": output_file,
        "filters_applied": filters_applied,
        "ffmpeg_error": result.get("stderr", ""),
        "returncode": result.get("returncode", -1),
    }


async def get_available_filters() -> Dict[str, Any]:
    """Get list of available FFmpeg video and audio filters."""
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    try:
        proc = await anyio.run_process(
            [ffmpeg_bin, "-filters"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        output = (proc.stdout or b"").decode("utf-8", errors="replace")
        video_filters: List[str] = []
        audio_filters: List[str] = []
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("Filters:") or stripped.startswith("---"):
                continue
            parts = stripped.split()
            if len(parts) >= 2:
                flags, name = parts[0], parts[1]
                if "V" in flags:
                    video_filters.append(name)
                if "A" in flags:
                    audio_filters.append(name)
        return {
            "status": "success",
            "video_filters": video_filters,
            "audio_filters": audio_filters,
            "filter_count": len(video_filters) + len(audio_filters),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
