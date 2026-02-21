"""
Canonical FFmpeg mux/demux engine.

Provides ffmpeg_mux and ffmpeg_demux for combining/separating media streams.

MCP tool wrapper: ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_mux_demux
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .ffmpeg_edit_engine import _validate_output_path, _run_ffmpeg
from .ffmpeg_info_engine import _validate_input_file, ffmpeg_probe

logger = logging.getLogger(__name__)


async def ffmpeg_mux(
    video_input: Optional[str] = None,
    audio_inputs: Optional[List[str]] = None,
    subtitle_inputs: Optional[List[str]] = None,
    output_file: str = "",
    output_format: Optional[str] = None,
    video_codec: str = "copy",
    audio_codec: str = "copy",
    subtitle_codec: str = "copy",
    map_streams: Optional[List[str]] = None,
    metadata: Optional[Dict[str, str]] = None,
    timeout: int = 300,
) -> Dict[str, Any]:
    """Mux (combine) separate video, audio, and subtitle streams into a single container."""
    if not output_file:
        return {"status": "error", "error": "Output file path is required"}

    inputs: List[str] = []
    for label, path in [("video", video_input)]:
        if path:
            if not _validate_input_file(path):
                return {"status": "error", "error": f"Video input file not found: {path}"}
            inputs.append(path)

    for audio_file in (audio_inputs or []):
        if not _validate_input_file(audio_file):
            return {"status": "error", "error": f"Audio input file not found: {audio_file}"}
        inputs.append(audio_file)

    for subtitle_file in (subtitle_inputs or []):
        if not _validate_input_file(subtitle_file):
            return {"status": "error", "error": f"Subtitle input file not found: {subtitle_file}"}
        inputs.append(subtitle_file)

    if not inputs:
        return {"status": "error", "error": "At least one input file is required"}
    if not _validate_output_path(output_file):
        return {"status": "error", "error": f"Output path not writable: {output_file}"}

    args: List[str] = []
    for f in inputs:
        args.extend(["-i", f])

    if map_streams:
        for mapping in map_streams:
            args.extend(["-map", mapping])
    else:
        if video_input:
            args.extend(["-map", "0:v"])
        audio_start = 1 if video_input else 0
        for i in range(len(audio_inputs or [])):
            args.extend(["-map", f"{audio_start + i}:a"])
        subtitle_start = audio_start + len(audio_inputs or [])
        for i in range(len(subtitle_inputs or [])):
            args.extend(["-map", f"{subtitle_start + i}:s"])

    args.extend(["-c:v", video_codec, "-c:a", audio_codec])
    if subtitle_inputs:
        args.extend(["-c:s", subtitle_codec])
    if metadata:
        for key, value in metadata.items():
            args.extend(["-metadata", f"{key}={value}"])
    if output_format:
        args.extend(["-f", output_format])
    args.extend(["-y", output_file])

    logger.info("Starting muxing to: %s", output_file)
    result = await _run_ffmpeg(args, timeout=timeout)
    if result["status"] == "success":
        output_info = await ffmpeg_probe(output_file)
        return {
            "status": "success",
            "message": "Media muxing completed successfully",
            "inputs": {"video": video_input, "audio": audio_inputs, "subtitle": subtitle_inputs},
            "output_file": output_file,
            "output_info": output_info,
            "command": result.get("command", ""),
        }
    return {
        "status": "error",
        "error": "FFmpeg muxing failed",
        "ffmpeg_error": result.get("stderr", ""),
        "command": result.get("command", ""),
        "returncode": result.get("returncode", -1),
    }


async def ffmpeg_demux(
    input_file: Union[str, Dict[str, Any]],
    output_dir: str,
    extract_video: bool = True,
    extract_audio: bool = True,
    extract_subtitles: bool = True,
    video_format: str = "mp4",
    audio_format: str = "mp3",
    subtitle_format: str = "srt",
    stream_selection: Optional[Dict[str, List[int]]] = None,
    timeout: int = 300,
) -> Dict[str, Any]:
    """Demux (separate) streams from a media container into separate files."""
    if isinstance(input_file, dict):
        input_path = input_file.get("file_path") or input_file.get("path")
        if not input_path:
            return {"status": "error", "error": "Dataset input must contain 'file_path' or 'path'"}
    else:
        input_path = str(input_file)

    if not _validate_input_file(input_path):
        return {"status": "error", "error": f"Input file not found: {input_path}"}

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    info_result = await ffmpeg_probe(input_path)
    if info_result.get("status") != "success":
        return {"status": "error", "error": f"Could not probe input: {info_result.get('error')}"}

    extracted: List[Dict[str, Any]] = []
    base = Path(input_path).stem

    video_streams = info_result.get("video_streams", [])
    audio_streams = info_result.get("audio_streams", [])
    subtitle_streams = info_result.get("subtitle_streams", [])

    if extract_video and video_streams:
        indices = (stream_selection or {}).get("video", list(range(len(video_streams))))
        for idx in indices:
            if idx < len(video_streams):
                out = output_path / f"{base}_video_{idx}.{video_format}"
                codec = "copy" if video_format == Path(input_path).suffix[1:] else "libx264"
                res = await _run_ffmpeg(
                    ["-i", input_path, "-map", f"0:v:{idx}", "-c:v", codec, "-an", "-y", str(out)],
                    timeout=timeout,
                )
                if res["status"] == "success":
                    extracted.append({"type": "video", "stream_index": idx, "file_path": str(out)})

    if extract_audio and audio_streams:
        indices = (stream_selection or {}).get("audio", list(range(len(audio_streams))))
        for idx in indices:
            if idx < len(audio_streams):
                out = output_path / f"{base}_audio_{idx}.{audio_format}"
                codec = "copy" if audio_format in ("mp3", "aac") else "libmp3lame"
                res = await _run_ffmpeg(
                    ["-i", input_path, "-map", f"0:a:{idx}", "-c:a", codec, "-vn", "-y", str(out)],
                    timeout=timeout,
                )
                if res["status"] == "success":
                    extracted.append({"type": "audio", "stream_index": idx, "file_path": str(out)})

    if extract_subtitles and subtitle_streams:
        indices = (stream_selection or {}).get("subtitle", list(range(len(subtitle_streams))))
        for idx in indices:
            if idx < len(subtitle_streams):
                out = output_path / f"{base}_subtitle_{idx}.{subtitle_format}"
                res = await _run_ffmpeg(
                    ["-i", input_path, "-map", f"0:s:{idx}", "-c:s", "copy", "-y", str(out)],
                    timeout=timeout,
                )
                if res["status"] == "success":
                    extracted.append({"type": "subtitle", "stream_index": idx, "file_path": str(out)})

    return {
        "status": "success",
        "message": "Media demuxing completed successfully",
        "input_file": input_path,
        "output_directory": output_dir,
        "extracted_files": extracted,
        "extracted_count": {
            "video": sum(1 for f in extracted if f["type"] == "video"),
            "audio": sum(1 for f in extracted if f["type"] == "audio"),
            "subtitle": sum(1 for f in extracted if f["type"] == "subtitle"),
        },
    }
