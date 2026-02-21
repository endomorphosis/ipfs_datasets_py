"""
Canonical FFmpeg info and analysis engine.

Provides ffmpeg_probe and ffmpeg_analyze for extracting detailed media file
information and performing quality analysis via FFprobe/FFmpeg.

MCP tool wrapper: ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_info
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import anyio

logger = logging.getLogger(__name__)

# Use the canonical FFmpegWrapper from processors.multimedia for delegated operations.
try:
    from ipfs_datasets_py.processors.multimedia import FFmpegWrapper as _FFmpegWrapper

    _ffmpeg_wrapper = _FFmpegWrapper(enable_logging=False)
    _FFMPEG_AVAILABLE = _ffmpeg_wrapper.is_available()
except Exception:
    _ffmpeg_wrapper = None  # type: ignore[assignment]
    _FFMPEG_AVAILABLE = False


def _ffprobe_binary() -> str:
    """Return the ffprobe binary path."""
    return shutil.which("ffprobe") or "ffprobe"


def _validate_input_file(file_path: str) -> bool:
    """Return True if the file exists and is readable."""
    try:
        p = Path(file_path)
        return p.exists() and p.is_file()
    except (OSError, PermissionError):
        return False


async def ffmpeg_probe(
    input_file: Union[str, Dict[str, Any]],
    show_format: bool = True,
    show_streams: bool = True,
    show_chapters: bool = False,
    show_frames: bool = False,
    frame_count: Optional[int] = None,
    select_streams: Optional[str] = None,
    include_metadata: bool = True,
) -> Dict[str, Any]:
    """
    Probe media file for detailed information using FFprobe.

    Args:
        input_file: Input media file path or dataset dict with 'file_path'/'path'
        show_format: Include format/container information
        show_streams: Include stream information
        show_chapters: Include chapter information
        show_frames: Include frame-level information
        frame_count: Number of frames to analyse (if show_frames=True)
        select_streams: Stream selector (e.g. 'v:0', 'a', 's:0')
        include_metadata: Include metadata tags

    Returns:
        Dict containing detailed media information
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

        ffprobe = _ffprobe_binary()
        cmd: List[str] = [ffprobe, "-v", "quiet", "-print_format", "json"]

        if show_format:
            cmd.append("-show_format")
        if show_streams:
            cmd.append("-show_streams")
        if show_chapters:
            cmd.append("-show_chapters")
        if show_frames:
            cmd.append("-show_frames")
            if frame_count:
                cmd.extend(["-read_intervals", f"%+#{frame_count}"])
        if select_streams:
            cmd.extend(["-select_streams", select_streams])

        cmd.append(input_path)

        proc = await anyio.run_process(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        if proc.returncode != 0:
            return {
                "status": "error",
                "error": "FFprobe failed",
                "stderr": (proc.stderr or b"").decode("utf-8", errors="replace"),
                "command": " ".join(cmd),
            }

        try:
            probe_data = json.loads((proc.stdout or b"").decode("utf-8"))
        except json.JSONDecodeError as exc:
            return {
                "status": "error",
                "error": f"Failed to parse FFprobe output: {exc}",
                "raw_output": (proc.stdout or b"").decode("utf-8", errors="replace")[:1000],
            }

        analysis: Dict[str, Any] = {
            "file_path": input_path,
            "file_size_bytes": Path(input_path).stat().st_size,
            "probe_data": probe_data,
        }

        if "format" in probe_data:
            fmt = probe_data["format"]
            analysis["format_analysis"] = {
                "container": fmt.get("format_name", "unknown"),
                "duration_seconds": float(fmt.get("duration", 0)),
                "size_bytes": int(fmt.get("size", 0)),
                "bitrate_bps": int(fmt.get("bit_rate", 0)),
                "tags": fmt.get("tags", {}),
            }

        if "streams" in probe_data:
            sa: Dict[str, list] = {
                "video_streams": [],
                "audio_streams": [],
                "subtitle_streams": [],
                "data_streams": [],
            }
            for stream in probe_data["streams"]:
                ctype = stream.get("codec_type", "").lower()
                if ctype == "video":
                    sa["video_streams"].append({
                        "index": stream.get("index"),
                        "codec": stream.get("codec_name"),
                        "profile": stream.get("profile"),
                        "width": stream.get("width"),
                        "height": stream.get("height"),
                        "aspect_ratio": stream.get("display_aspect_ratio"),
                        "pixel_format": stream.get("pix_fmt"),
                        "frame_rate": stream.get("avg_frame_rate"),
                        "bitrate": stream.get("bit_rate"),
                        "duration": stream.get("duration"),
                        "frame_count": stream.get("nb_frames"),
                        "color_space": stream.get("color_space"),
                        "color_range": stream.get("color_range"),
                    })
                elif ctype == "audio":
                    sa["audio_streams"].append({
                        "index": stream.get("index"),
                        "codec": stream.get("codec_name"),
                        "sample_rate": stream.get("sample_rate"),
                        "channels": stream.get("channels"),
                        "channel_layout": stream.get("channel_layout"),
                        "sample_format": stream.get("sample_fmt"),
                        "bitrate": stream.get("bit_rate"),
                        "duration": stream.get("duration"),
                        "language": stream.get("tags", {}).get("language"),
                    })
                elif ctype == "subtitle":
                    sa["subtitle_streams"].append({
                        "index": stream.get("index"),
                        "codec": stream.get("codec_name"),
                        "language": stream.get("tags", {}).get("language"),
                        "title": stream.get("tags", {}).get("title"),
                    })
                else:
                    sa["data_streams"].append({
                        "index": stream.get("index"),
                        "codec_type": ctype,
                        "codec": stream.get("codec_name"),
                    })
            analysis["stream_analysis"] = sa

        if "chapters" in probe_data:
            analysis["chapter_analysis"] = [
                {
                    "id": ch.get("id"),
                    "start_time": float(ch.get("start_time", 0)),
                    "end_time": float(ch.get("end_time", 0)),
                    "title": ch.get("tags", {}).get("title"),
                }
                for ch in probe_data["chapters"]
            ]

        if "frames" in probe_data and show_frames:
            analysis["frame_analysis"] = {
                "frame_count": len(probe_data["frames"]),
                "sample_frames": probe_data["frames"][:10],
            }

        return {
            "status": "success",
            "message": "Media probe completed successfully",
            "analysis": analysis,
            "command": " ".join(cmd),
        }

    except Exception as exc:
        logger.error(f"Error in ffmpeg_probe: {exc}")
        return {"status": "error", "error": str(exc), "input_file": str(input_file)}


async def ffmpeg_analyze(
    input_file: Union[str, Dict[str, Any]],
    analysis_type: str = "comprehensive",
    video_analysis: bool = True,
    audio_analysis: bool = True,
    quality_metrics: bool = True,
    performance_metrics: bool = True,
    sample_duration: Optional[str] = None,
    output_report: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Perform comprehensive analysis of media file quality and characteristics.

    Args:
        input_file: Input media file path or dataset dict
        analysis_type: One of 'basic', 'comprehensive', 'quality', 'performance'
        video_analysis: Include video stream analysis
        audio_analysis: Include audio stream analysis
        quality_metrics: Calculate quality metrics
        performance_metrics: Calculate performance metrics
        sample_duration: Duration of sample to analyse (e.g. '00:01:00')
        output_report: Path to save detailed JSON report

    Returns:
        Dict containing comprehensive analysis results
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

        probe_result = await ffmpeg_probe(
            input_file=input_path,
            show_format=True,
            show_streams=True,
            show_chapters=True,
            include_metadata=True,
        )

        if probe_result["status"] != "success":
            return probe_result

        analysis = probe_result["analysis"]

        if analysis_type in ("comprehensive", "quality") and quality_metrics:
            if video_analysis and analysis.get("stream_analysis", {}).get("video_streams"):
                analysis["video_quality"] = await _analyze_video_quality(input_path, sample_duration)
            if audio_analysis and analysis.get("stream_analysis", {}).get("audio_streams"):
                analysis["audio_quality"] = await _analyze_audio_quality(input_path, sample_duration)

        if analysis_type in ("comprehensive", "performance") and performance_metrics:
            analysis["performance_metrics"] = await _analyze_performance(input_path)

        if analysis_type in ("comprehensive", "quality"):
            analysis["compression_analysis"] = _analyze_compression(analysis)

        analysis["summary"] = _generate_analysis_summary(analysis)

        if output_report:
            await _save_analysis_report(analysis, output_report)

        return {
            "status": "success",
            "message": "Media analysis completed successfully",
            "analysis_type": analysis_type,
            "analysis": analysis,
        }

    except Exception as exc:
        logger.error(f"Error in ffmpeg_analyze: {exc}")
        return {"status": "error", "error": str(exc), "input_file": str(input_file)}


async def _analyze_video_quality(
    input_path: str, sample_duration: Optional[str] = None
) -> Dict[str, Any]:
    """Analyse video quality metrics via FFmpeg stderr output."""
    try:
        ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
        args = [ffmpeg_bin, "-i", input_path]

        if sample_duration:
            args.extend(["-t", sample_duration])

        args.extend(["-vf", "blackdetect=d=2:pix_th=0.00,select=gt(scene\\,0.3)"])
        args.extend(["-f", "null", "-"])

        proc = await anyio.run_process(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        stderr_text = (proc.stderr or b"").decode("utf-8", errors="replace")

        return {
            "analysis_performed": True,
            "sample_duration": sample_duration,
            "blackframes_detected": "blackdetect" in stderr_text,
            "scene_changes": stderr_text.count("pts_time") if stderr_text else 0,
        }
    except Exception as exc:
        return {"error": str(exc), "analysis_performed": False}


async def _analyze_audio_quality(
    input_path: str, sample_duration: Optional[str] = None
) -> Dict[str, Any]:
    """Analyse audio quality metrics via FFmpeg."""
    try:
        ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
        args = [ffmpeg_bin, "-i", input_path]

        if sample_duration:
            args.extend(["-t", sample_duration])

        args.extend(["-af", "astats=metadata=1:reset=1,ametadata=print:file=-"])
        args.extend(["-f", "null", "-"])

        proc = await anyio.run_process(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        stderr_text = (proc.stderr or b"").decode("utf-8", errors="replace")

        return {
            "analysis_performed": True,
            "sample_duration": sample_duration,
            "has_audio_stats": "astats" in stderr_text,
            "silence_detected": "silence_start" in stderr_text,
        }
    except Exception as exc:
        return {"error": str(exc), "analysis_performed": False}


async def _analyze_performance(input_path: str) -> Dict[str, Any]:
    """Benchmark decode performance for the first 10 seconds."""
    try:
        ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
        args = [ffmpeg_bin, "-i", input_path, "-t", "10", "-f", "null", "-"]

        t0 = time.monotonic()
        proc = await anyio.run_process(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        elapsed = time.monotonic() - t0

        return {
            "decode_benchmark": {
                "sample_duration": 10,
                "decode_time_seconds": round(elapsed, 3),
                "realtime_factor": round(10 / elapsed, 2) if elapsed > 0 else 0,
                "success": proc.returncode == 0,
            }
        }
    except Exception as exc:
        return {"error": str(exc)}


def _analyze_compression(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Estimate compression efficiency from probe data."""
    try:
        format_info = analysis.get("format_analysis", {})
        video_streams = analysis.get("stream_analysis", {}).get("video_streams", [])

        if not video_streams:
            return {"error": "No video streams found"}

        video = video_streams[0]
        duration = float(format_info.get("duration_seconds", 0))
        bitrate = int(format_info.get("bitrate_bps", 0))
        width = video.get("width") or 0
        height = video.get("height") or 0

        if duration > 0 and width > 0 and height > 0:
            pixels_per_second = width * height * 30
            bpp = bitrate / pixels_per_second if pixels_per_second > 0 else 0
            return {
                "duration_seconds": duration,
                "average_bitrate_bps": bitrate,
                "resolution": f"{width}x{height}",
                "bits_per_pixel": round(bpp, 4),
                "compression_efficiency": (
                    "high" if bpp < 0.1 else ("medium" if bpp < 0.2 else "low")
                ),
            }

        return {"error": "Insufficient data for compression analysis"}
    except Exception as exc:
        return {"error": str(exc)}


def _generate_analysis_summary(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Build a human-readable summary of probe/analysis data."""
    try:
        fmt = analysis.get("format_analysis", {})
        sa = analysis.get("stream_analysis", {})

        summary: Dict[str, Any] = {
            "file_type": fmt.get("container", "unknown"),
            "duration": fmt.get("duration_seconds", 0),
            "file_size_mb": round(analysis.get("file_size_bytes", 0) / 1024 / 1024, 2),
            "video_streams": len(sa.get("video_streams", [])),
            "audio_streams": len(sa.get("audio_streams", [])),
            "subtitle_streams": len(sa.get("subtitle_streams", [])),
            "has_chapters": len(analysis.get("chapter_analysis", [])) > 0,
        }

        if sa.get("video_streams"):
            v = sa["video_streams"][0]
            summary["video"] = {
                "codec": v.get("codec"),
                "resolution": (
                    f"{v.get('width')}x{v.get('height')}" if v.get("width") else "unknown"
                ),
                "frame_rate": v.get("frame_rate"),
                "bitrate": v.get("bitrate"),
            }

        if sa.get("audio_streams"):
            a = sa["audio_streams"][0]
            summary["audio"] = {
                "codec": a.get("codec"),
                "sample_rate": a.get("sample_rate"),
                "channels": a.get("channels"),
                "bitrate": a.get("bitrate"),
            }

        return summary
    except Exception as exc:
        return {"error": str(exc)}


async def _save_analysis_report(analysis: Dict[str, Any], output_path: str) -> None:
    """Persist an analysis dict to a JSON file."""
    try:
        with open(output_path, "w") as fh:
            json.dump(analysis, fh, indent=2, default=str)
        logger.info(f"Analysis report saved to: {output_path}")
    except Exception as exc:
        logger.error(f"Failed to save analysis report: {exc}")


__all__ = [
    "ffmpeg_probe",
    "ffmpeg_analyze",
    "_analyze_video_quality",
    "_analyze_audio_quality",
    "_analyze_performance",
    "_analyze_compression",
    "_generate_analysis_summary",
    "_save_analysis_report",
]
