"""
Canonical FFmpeg editing engine.

Provides ffmpeg_cut, ffmpeg_splice, and ffmpeg_concat for precise media
file editing via the FFmpeg command-line tool.

MCP tool wrapper: ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_edit
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import anyio

from .ffmpeg_info_engine import _validate_input_file, ffmpeg_probe

logger = logging.getLogger(__name__)


class FFmpegEditError(Exception):
    """Raised when an FFmpeg edit operation fails."""


def _validate_output_path(output_path: str) -> bool:
    """Return True if the parent directory of the output path is writable."""
    try:
        p = Path(output_path)
        return p.parent.exists() and p.parent.is_dir()
    except (OSError, PermissionError):
        return False


def _parse_time(time_str: str) -> float:
    """Parse a time string ('HH:MM:SS', 'MM:SS', or raw seconds) to float."""
    parts = time_str.strip().split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


async def _run_ffmpeg(args: List[str], timeout: int = 600) -> Dict[str, Any]:
    """Run an ffmpeg command and return a status dict."""
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    full_args = [ffmpeg_bin] + args
    try:
        proc = await anyio.run_process(
            full_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode == 0:
            return {
                "status": "success",
                "command": " ".join(full_args),
                "stderr": (proc.stderr or b"").decode("utf-8", errors="replace"),
            }
        return {
            "status": "error",
            "returncode": proc.returncode,
            "stderr": (proc.stderr or b"").decode("utf-8", errors="replace"),
            "command": " ".join(full_args),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc), "command": " ".join(full_args)}


async def ffmpeg_cut(
    input_file: Union[str, Dict[str, Any]],
    output_file: str,
    start_time: str,
    end_time: Optional[str] = None,
    duration: Optional[str] = None,
    video_codec: str = "copy",
    audio_codec: str = "copy",
    accurate_seek: bool = True,
    timeout: int = 300,
) -> Dict[str, Any]:
    """
    Cut/trim a segment from a media file using FFmpeg.

    Args:
        input_file: Input media file path or dataset dict with 'file_path'/'path'
        output_file: Output file path for the cut segment
        start_time: Start time (e.g. '00:01:30', '90', '1:30')
        end_time: End time (e.g. '00:05:00', '300') — exclusive with *duration*
        duration: Duration instead of end time — exclusive with *end_time*
        video_codec: Video codec ('copy' for lossless)
        audio_codec: Audio codec ('copy' for lossless)
        accurate_seek: Use accurate but slower seeking
        timeout: Processing timeout in seconds

    Returns:
        Dict containing cutting results
    """
    try:
        if isinstance(input_file, dict):
            input_path = input_file.get("file_path") or input_file.get("path")
            if not input_path:
                return {
                    "status": "error",
                    "error": "Dataset input must contain 'file_path' or 'path' field",
                }
        else:
            input_path = str(input_file)

        if not _validate_input_file(input_path):
            return {"status": "error", "error": f"Input file not found: {input_path}"}

        if not _validate_output_path(output_file):
            return {"status": "error", "error": f"Output path not writable: {output_file}"}

        if not end_time and not duration:
            return {"status": "error", "error": "Either end_time or duration must be specified"}
        if end_time and duration:
            return {"status": "error", "error": "Specify either end_time or duration, not both"}

        try:
            start_seconds = _parse_time(start_time)
            if end_time:
                end_seconds = _parse_time(end_time)
                duration_seconds = end_seconds - start_seconds
            else:
                duration_seconds = _parse_time(duration)  # type: ignore[arg-type]
                end_seconds = start_seconds + duration_seconds
        except (ValueError, IndexError) as exc:
            return {"status": "error", "error": f"Invalid time format: {exc}"}

        if duration_seconds <= 0:
            return {"status": "error", "error": "Duration must be positive"}

        args: List[str] = []
        if accurate_seek:
            args.extend(["-ss", str(start_seconds), "-i", input_path])
        else:
            args.extend(["-i", input_path, "-ss", str(start_seconds)])

        args.extend(["-t", str(duration_seconds)])
        args.extend(["-c:v", video_codec, "-c:a", audio_codec])
        if video_codec == "copy" and audio_codec == "copy":
            args.extend(["-avoid_negative_ts", "make_zero"])
        args.extend(["-y", output_file])

        logger.info(f"Cutting: {start_time} to {end_time or f'+{duration}'}")
        result = await _run_ffmpeg(args, timeout=timeout)

        if result["status"] == "success":
            output_info = await ffmpeg_probe(input_file=output_file)
            return {
                "status": "success",
                "message": "Media cutting completed successfully",
                "input_file": input_path,
                "output_file": output_file,
                "segment_info": {
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration": duration,
                    "start_seconds": start_seconds,
                    "end_seconds": end_seconds,
                    "duration_seconds": duration_seconds,
                },
                "output_info": output_info,
                "command": result.get("command", ""),
            }
        return {
            "status": "error",
            "error": "FFmpeg cutting failed",
            "ffmpeg_error": result.get("stderr", ""),
            "command": result.get("command", ""),
            "returncode": result.get("returncode", -1),
        }

    except Exception as exc:
        logger.error(f"Error in ffmpeg_cut: {exc}")
        return {"status": "error", "error": str(exc), "input_file": str(input_file)}


async def ffmpeg_splice(
    input_files: List[Union[str, Dict[str, Any]]],
    output_file: str,
    segments: List[Dict[str, Any]],
    video_codec: str = "libx264",
    audio_codec: str = "aac",
    transition_type: str = "cut",
    transition_duration: float = 0.0,
    timeout: int = 600,
) -> Dict[str, Any]:
    """
    Splice multiple segments from various files into a single output file.

    Args:
        input_files: List of input media files (paths or dataset dicts)
        output_file: Output file path
        segments: List of segment definitions with 'source_file', 'start_time',
                  and 'end_time' (or 'duration') keys
        video_codec: Video codec for output
        audio_codec: Audio codec for output
        transition_type: Transition type ('cut', 'fade', 'crossfade')
        transition_duration: Transition duration in seconds
        timeout: Processing timeout in seconds

    Returns:
        Dict containing splicing results
    """
    try:
        if not input_files:
            return {"status": "error", "error": "At least one input file is required"}
        if not segments:
            return {"status": "error", "error": "At least one segment definition is required"}

        validated_inputs: List[str] = []
        for inp in input_files:
            if isinstance(inp, dict):
                ip = inp.get("file_path") or inp.get("path")
                if not ip:
                    return {
                        "status": "error",
                        "error": "Dataset input must contain 'file_path' or 'path' field",
                    }
            else:
                ip = str(inp)
            if not _validate_input_file(ip):
                return {"status": "error", "error": f"Input file not found: {ip}"}
            validated_inputs.append(ip)

        if not _validate_output_path(output_file):
            return {"status": "error", "error": f"Output path not writable: {output_file}"}

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            segment_files: List[str] = []

            for i, seg in enumerate(segments):
                source_file = seg.get("source_file")
                start_time = seg.get("start_time")
                end_time = seg.get("end_time")
                dur = seg.get("duration")

                if source_file not in validated_inputs:
                    return {"status": "error", "error": f"Source file not in input list: {source_file}"}
                if not start_time:
                    return {"status": "error", "error": f"Segment {i}: start_time is required"}

                seg_out = str(tmp_path / f"segment_{i:03d}.mp4")
                cut_result = await ffmpeg_cut(
                    input_file=source_file,
                    output_file=seg_out,
                    start_time=start_time,
                    end_time=end_time,
                    duration=dur,
                    video_codec="libx264",
                    audio_codec="aac",
                    timeout=timeout // max(len(segments), 1),
                )
                if cut_result["status"] != "success":
                    return {
                        "status": "error",
                        "error": f"Failed to extract segment {i}: {cut_result.get('error')}",
                    }
                segment_files.append(seg_out)

            concat_result = await ffmpeg_concat(
                input_files=segment_files,
                output_file=output_file,
                video_codec=video_codec,
                audio_codec=audio_codec,
                method="file_list",
                timeout=timeout,
            )

            if concat_result["status"] == "success":
                return {
                    "status": "success",
                    "message": "Media splicing completed successfully",
                    "input_files": validated_inputs,
                    "output_file": output_file,
                    "segments_processed": len(segments),
                    "transition_type": transition_type,
                    "transition_duration": transition_duration,
                    "concat_result": concat_result,
                }
            return {
                "status": "error",
                "error": "Failed to concatenate segments",
                "concat_error": concat_result.get("error"),
            }

    except Exception as exc:
        logger.error(f"Error in ffmpeg_splice: {exc}")
        return {"status": "error", "error": str(exc)}


async def ffmpeg_concat(
    input_files: List[Union[str, Dict[str, Any]]],
    output_file: str,
    video_codec: str = "copy",
    audio_codec: str = "copy",
    method: str = "filter",
    safe_mode: bool = True,
    timeout: int = 600,
) -> Dict[str, Any]:
    """
    Concatenate multiple media files into a single output file.

    Args:
        input_files: List of input media files (paths or dataset dicts)
        output_file: Output file path
        video_codec: Video codec ('copy' for no re-encoding)
        audio_codec: Audio codec ('copy' for no re-encoding)
        method: 'filter' (most compatible), 'demuxer' (fastest), or 'file_list'
        safe_mode: Enable safe file-path handling for demuxer/file_list methods
        timeout: Processing timeout in seconds

    Returns:
        Dict containing concatenation results
    """
    try:
        if not input_files:
            return {"status": "error", "error": "At least one input file is required"}

        validated_inputs: List[str] = []
        for inp in input_files:
            if isinstance(inp, dict):
                ip = inp.get("file_path") or inp.get("path")
                if not ip:
                    return {
                        "status": "error",
                        "error": "Dataset input must contain 'file_path' or 'path' field",
                    }
            else:
                ip = str(inp)
            if not _validate_input_file(ip):
                return {"status": "error", "error": f"Input file not found: {ip}"}
            validated_inputs.append(ip)

        if not _validate_output_path(output_file):
            return {"status": "error", "error": f"Output path not writable: {output_file}"}

        args: List[str] = []
        concat_file: Optional[str] = None

        if method == "demuxer":
            tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
            for p in validated_inputs:
                tmp.write(f"file '{p}'\n")
            tmp.close()
            concat_file = tmp.name
            args = ["-f", "concat"]
            if safe_mode:
                args += ["-safe", "0"]
            args += ["-i", concat_file, "-c:v", video_codec, "-c:a", audio_codec]

        elif method == "filter":
            for p in validated_inputs:
                args += ["-i", p]
            n = len(validated_inputs)
            filter_in = "".join(f"[{i}:v][{i}:a]" for i in range(n))
            args += [
                "-filter_complex", f"{filter_in}concat=n={n}:v=1:a=1[outv][outa]",
                "-map", "[outv]", "-map", "[outa]",
                "-c:v", video_codec, "-c:a", audio_codec,
            ]

        elif method == "file_list":
            tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
            for p in validated_inputs:
                tmp.write(f"file '{p}'\n")
            tmp.close()
            concat_file = tmp.name
            args = ["-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy"]

        else:
            return {"status": "error", "error": f"Unknown concatenation method: {method}"}

        args += ["-y", output_file]

        logger.info(f"Concatenating {len(validated_inputs)} files using {method} method")
        result = await _run_ffmpeg(args, timeout=timeout)

        if concat_file:
            try:
                Path(concat_file).unlink()
            except OSError:
                pass

        if result["status"] == "success":
            output_info = await ffmpeg_probe(input_file=output_file)
            return {
                "status": "success",
                "message": "Media concatenation completed successfully",
                "input_files": validated_inputs,
                "output_file": output_file,
                "method": method,
                "input_count": len(validated_inputs),
                "output_info": output_info,
                "command": result.get("command", ""),
            }
        return {
            "status": "error",
            "error": "FFmpeg concatenation failed",
            "ffmpeg_error": result.get("stderr", ""),
            "command": result.get("command", ""),
            "returncode": result.get("returncode", -1),
        }

    except Exception as exc:
        logger.error(f"Error in ffmpeg_concat: {exc}")
        return {"status": "error", "error": str(exc)}


__all__ = ["ffmpeg_cut", "ffmpeg_splice", "ffmpeg_concat"]
