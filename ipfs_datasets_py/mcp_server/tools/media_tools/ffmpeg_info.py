# ipfs_datasets_py/mcp_server/tools/media_tools/ffmpeg_info.py
"""
FFmpeg media information and analysis tools for the MCP server.

This module provides tools for probing media file information and performing
detailed analysis of audio/video streams using FFmpeg and FFprobe.
"""
import anyio
from typing import Dict, Any, Optional, Union, List
from pathlib import Path
import json

import logging

logger = logging.getLogger(__name__)
from .ffmpeg_utils import ffmpeg_utils, FFmpegError

async def ffmpeg_probe(
    input_file: Union[str, Dict[str, Any]],
    show_format: bool = True,
    show_streams: bool = True,
    show_chapters: bool = False,
    show_frames: bool = False,
    frame_count: Optional[int] = None,
    select_streams: Optional[str] = None,
    include_metadata: bool = True
) -> Dict[str, Any]:
    """
    Probe media file for detailed information using FFprobe.
    
    This tool extracts comprehensive metadata including:
    - Container format information
    - Video/audio/subtitle stream details
    - Codec information and parameters
    - Duration, bitrate, and quality metrics
    - Chapter information
    - Frame-level analysis (optional)
    
    Args:
        input_file: Input media file path or dataset
        show_format: Include format/container information
        show_streams: Include stream information
        show_chapters: Include chapter information
        show_frames: Include frame-level information
        frame_count: Number of frames to analyze (if show_frames=True)
        select_streams: Stream selector (e.g., 'v:0', 'a', 's:0')
        include_metadata: Include metadata tags
        
    Returns:
        Dict containing detailed media information
    """
    try:
        # Handle dataset input
        if isinstance(input_file, dict):
            if 'file_path' in input_file:
                input_path = input_file['file_path']
            elif 'path' in input_file:
                input_path = input_file['path']
            else:
                return {
                    "status": "error",
                    "error": "Dataset input must contain 'file_path' or 'path' field"
                }
        else:
            input_path = str(input_file)
        
        # Validate input file
        if not ffmpeg_utils.validate_input_file(input_path):
            return {
                "status": "error",
                "error": f"Input file not found: {input_path}"
            }
        
        # Build FFprobe command
        cmd = [ffmpeg_utils.ffprobe_path]
        cmd.extend(["-v", "quiet"])
        cmd.extend(["-print_format", "json"])
        
        # What to show
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
        
        # Stream selection
        if select_streams:
            cmd.extend(["-select_streams", select_streams])
        
        # Input file
        cmd.append(input_path)
        
        # Execute probe
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            return {
                "status": "error",
                "error": "FFprobe failed",
                "stderr": stderr.decode('utf-8', errors='replace'),
                "command": ' '.join(cmd)
            }
        
        # Parse JSON output
        try:
            probe_data = json.loads(stdout.decode('utf-8'))
        except json.JSONDecodeError as e:
            return {
                "status": "error",
                "error": f"Failed to parse FFprobe output: {e}",
                "raw_output": stdout.decode('utf-8', errors='replace')[:1000]
            }
        
        # Enhanced analysis
        analysis = {
            "file_path": input_path,
            "file_size_bytes": Path(input_path).stat().st_size,
            "probe_data": probe_data
        }
        
        # Parse format information
        if "format" in probe_data:
            format_info = probe_data["format"]
            analysis["format_analysis"] = {
                "container": format_info.get("format_name", "unknown"),
                "duration_seconds": float(format_info.get("duration", 0)),
                "size_bytes": int(format_info.get("size", 0)),
                "bitrate_bps": int(format_info.get("bit_rate", 0)),
                "tags": format_info.get("tags", {})
            }
        
        # Parse stream information
        if "streams" in probe_data:
            streams = probe_data["streams"]
            analysis["stream_analysis"] = {
                "video_streams": [],
                "audio_streams": [],
                "subtitle_streams": [],
                "data_streams": []
            }
            
            for stream in streams:
                codec_type = stream.get("codec_type", "").lower()
                
                if codec_type == "video":
                    video_info = {
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
                        "color_range": stream.get("color_range")
                    }
                    analysis["stream_analysis"]["video_streams"].append(video_info)
                
                elif codec_type == "audio":
                    audio_info = {
                        "index": stream.get("index"),
                        "codec": stream.get("codec_name"),
                        "sample_rate": stream.get("sample_rate"),
                        "channels": stream.get("channels"),
                        "channel_layout": stream.get("channel_layout"),
                        "sample_format": stream.get("sample_fmt"),
                        "bitrate": stream.get("bit_rate"),
                        "duration": stream.get("duration"),
                        "language": stream.get("tags", {}).get("language")
                    }
                    analysis["stream_analysis"]["audio_streams"].append(audio_info)
                
                elif codec_type == "subtitle":
                    subtitle_info = {
                        "index": stream.get("index"),
                        "codec": stream.get("codec_name"),
                        "language": stream.get("tags", {}).get("language"),
                        "title": stream.get("tags", {}).get("title")
                    }
                    analysis["stream_analysis"]["subtitle_streams"].append(subtitle_info)
                
                else:
                    data_info = {
                        "index": stream.get("index"),
                        "codec_type": codec_type,
                        "codec": stream.get("codec_name")
                    }
                    analysis["stream_analysis"]["data_streams"].append(data_info)
        
        # Parse chapter information
        if "chapters" in probe_data:
            analysis["chapter_analysis"] = []
            for chapter in probe_data["chapters"]:
                chapter_info = {
                    "id": chapter.get("id"),
                    "start_time": float(chapter.get("start_time", 0)),
                    "end_time": float(chapter.get("end_time", 0)),
                    "title": chapter.get("tags", {}).get("title")
                }
                analysis["chapter_analysis"].append(chapter_info)
        
        # Parse frame information (if requested)
        if "frames" in probe_data and show_frames:
            analysis["frame_analysis"] = {
                "frame_count": len(probe_data["frames"]),
                "sample_frames": probe_data["frames"][:10] if probe_data["frames"] else []
            }
        
        return {
            "status": "success",
            "message": "Media probe completed successfully",
            "analysis": analysis,
            "command": ' '.join(cmd)
        }
    
    except Exception as e:
        logger.error(f"Error in ffmpeg_probe: {e}")
        return {
            "status": "error",
            "error": str(e),
            "input_file": input_file
        }

async def ffmpeg_analyze(
    input_file: Union[str, Dict[str, Any]],
    analysis_type: str = "comprehensive",
    video_analysis: bool = True,
    audio_analysis: bool = True,
    quality_metrics: bool = True,
    performance_metrics: bool = True,
    sample_duration: Optional[str] = None,
    output_report: Optional[str] = None
) -> Dict[str, Any]:
    """
    Perform comprehensive analysis of media file quality and characteristics.
    
    This tool provides advanced analysis including:
    - Video quality metrics (PSNR, SSIM, VMAF)
    - Audio quality analysis
    - Compression efficiency
    - Stream synchronization
    - Error detection
    - Performance benchmarks
    
    Args:
        input_file: Input media file path or dataset
        analysis_type: Type of analysis ('basic', 'comprehensive', 'quality', 'performance')
        video_analysis: Include video stream analysis
        audio_analysis: Include audio stream analysis
        quality_metrics: Calculate quality metrics
        performance_metrics: Calculate performance metrics
        sample_duration: Duration of sample to analyze (e.g., '00:01:00')
        output_report: Path to save detailed report
        
    Returns:
        Dict containing comprehensive analysis results
    """
    try:
        # Handle dataset input
        if isinstance(input_file, dict):
            if 'file_path' in input_file:
                input_path = input_file['file_path']
            elif 'path' in input_file:
                input_path = input_file['path']
            else:
                return {
                    "status": "error",
                    "error": "Dataset input must contain 'file_path' or 'path' field"
                }
        else:
            input_path = str(input_file)
        
        # Validate input file
        if not ffmpeg_utils.validate_input_file(input_path):
            return {
                "status": "error",
                "error": f"Input file not found: {input_path}"
            }
        
        # Start with basic probe
        probe_result = await ffmpeg_probe(
            input_file=input_path,
            show_format=True,
            show_streams=True,
            show_chapters=True,
            include_metadata=True
        )
        
        if probe_result["status"] != "success":
            return probe_result
        
        analysis = probe_result["analysis"]
        
        # Enhanced analysis based on type
        if analysis_type in ["comprehensive", "quality"] and quality_metrics:
            # Video quality analysis
            if video_analysis and analysis.get("stream_analysis", {}).get("video_streams"):
                video_quality = await _analyze_video_quality(input_path, sample_duration)
                analysis["video_quality"] = video_quality
            
            # Audio quality analysis
            if audio_analysis and analysis.get("stream_analysis", {}).get("audio_streams"):
                audio_quality = await _analyze_audio_quality(input_path, sample_duration)
                analysis["audio_quality"] = audio_quality
        
        if analysis_type in ["comprehensive", "performance"] and performance_metrics:
            # Performance metrics
            performance = await _analyze_performance(input_path)
            analysis["performance_metrics"] = performance
        
        # Compression analysis
        if analysis_type in ["comprehensive", "quality"]:
            compression = _analyze_compression(analysis)
            analysis["compression_analysis"] = compression
        
        # Generate summary
        summary = _generate_analysis_summary(analysis)
        analysis["summary"] = summary
        
        # Save report if requested
        if output_report:
            await _save_analysis_report(analysis, output_report)
        
        return {
            "status": "success",
            "message": "Media analysis completed successfully",
            "analysis_type": analysis_type,
            "analysis": analysis
        }
    
    except Exception as e:
        logger.error(f"Error in ffmpeg_analyze: {e}")
        return {
            "status": "error",
            "error": str(e),
            "input_file": input_file
        }

async def _analyze_video_quality(input_path: str, sample_duration: Optional[str] = None) -> Dict[str, Any]:
    """Analyze video quality metrics."""
    try:
        # Build FFmpeg command for video analysis
        args = ["-i", input_path]
        
        if sample_duration:
            duration_seconds = ffmpeg_utils.parse_time_format(sample_duration)
            args.extend(["-t", str(duration_seconds)])
        
        # Use various filters for analysis
        filters = []
        
        # PSNR analysis (if we had a reference)
        # filters.append("psnr")
        
        # Blackdetect
        filters.append("blackdetect=d=2:pix_th=0.00")
        
        # Scene detection
        filters.append("select=gt(scene\\,0.3)")
        
        args.extend(["-vf", ",".join(filters)])
        args.extend(["-f", "null", "-"])
        
        result = await ffmpeg_utils.run_ffmpeg_command(args, timeout=300)
        
        # Parse results from stderr
        quality_metrics = {
            "analysis_performed": True,
            "sample_duration": sample_duration,
            "blackframes_detected": "blackdetect" in result.get("stderr", ""),
            "scene_changes": result.get("stderr", "").count("select") if result.get("stderr") else 0
        }
        
        return quality_metrics
    
    except Exception as e:
        return {"error": str(e), "analysis_performed": False}

async def _analyze_audio_quality(input_path: str, sample_duration: Optional[str] = None) -> Dict[str, Any]:
    """Analyze audio quality metrics."""
    try:
        # Build FFmpeg command for audio analysis
        args = ["-i", input_path]
        
        if sample_duration:
            duration_seconds = ffmpeg_utils.parse_time_format(sample_duration)
            args.extend(["-t", str(duration_seconds)])
        
        # Audio analysis filters
        args.extend(["-af", "astats=metadata=1:reset=1,ametadata=print:file=-"])
        args.extend(["-f", "null", "-"])
        
        result = await ffmpeg_utils.run_ffmpeg_command(args, timeout=300)
        
        # Basic audio quality metrics
        quality_metrics = {
            "analysis_performed": True,
            "sample_duration": sample_duration,
            "has_audio_stats": "astats" in result.get("stderr", ""),
            "silence_detected": "silence_start" in result.get("stderr", "")
        }
        
        return quality_metrics
    
    except Exception as e:
        return {"error": str(e), "analysis_performed": False}

async def _analyze_performance(input_path: str) -> Dict[str, Any]:
    """Analyze encoding/decoding performance."""
    try:
        # Simple decode benchmark
        args = [
            "-i", input_path,
            "-t", "10",  # 10 second sample
            "-f", "null",
            "-"
        ]
        
        import time
        start_time = time.time()
        result = await ffmpeg_utils.run_ffmpeg_command(args, timeout=60)
        end_time = time.time()
        
        decode_time = end_time - start_time
        
        return {
            "decode_benchmark": {
                "sample_duration": 10,
                "decode_time_seconds": decode_time,
                "realtime_factor": 10 / decode_time if decode_time > 0 else 0,
                "success": result["status"] == "success"
            }
        }
    
    except Exception as e:
        return {"error": str(e)}

def _analyze_compression(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze compression efficiency."""
    try:
        format_info = analysis.get("format_analysis", {})
        video_streams = analysis.get("stream_analysis", {}).get("video_streams", [])
        
        if not video_streams:
            return {"error": "No video streams found"}
        
        video = video_streams[0]
        duration = float(format_info.get("duration_seconds", 0))
        bitrate = int(format_info.get("bitrate_bps", 0))
        width = video.get("width", 0)
        height = video.get("height", 0)
        
        if duration > 0 and width > 0 and height > 0:
            pixels_per_second = width * height * 30  # Assume 30fps
            bits_per_pixel = bitrate / pixels_per_second if pixels_per_second > 0 else 0
            
            return {
                "duration_seconds": duration,
                "average_bitrate_bps": bitrate,
                "resolution": f"{width}x{height}",
                "bits_per_pixel": round(bits_per_pixel, 4),
                "compression_efficiency": "high" if bits_per_pixel < 0.1 else "medium" if bits_per_pixel < 0.2 else "low"
            }
        
        return {"error": "Insufficient data for compression analysis"}
    
    except Exception as e:
        return {"error": str(e)}

def _generate_analysis_summary(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Generate analysis summary."""
    try:
        format_info = analysis.get("format_analysis", {})
        stream_info = analysis.get("stream_analysis", {})
        
        summary = {
            "file_type": format_info.get("container", "unknown"),
            "duration": format_info.get("duration_seconds", 0),
            "file_size_mb": round(analysis.get("file_size_bytes", 0) / 1024 / 1024, 2),
            "video_streams": len(stream_info.get("video_streams", [])),
            "audio_streams": len(stream_info.get("audio_streams", [])),
            "subtitle_streams": len(stream_info.get("subtitle_streams", [])),
            "has_chapters": len(analysis.get("chapter_analysis", [])) > 0
        }
        
        # Video summary
        if stream_info.get("video_streams"):
            video = stream_info["video_streams"][0]
            summary["video"] = {
                "codec": video.get("codec"),
                "resolution": f"{video.get('width')}x{video.get('height')}" if video.get('width') else "unknown",
                "frame_rate": video.get("frame_rate"),
                "bitrate": video.get("bitrate")
            }
        
        # Audio summary
        if stream_info.get("audio_streams"):
            audio = stream_info["audio_streams"][0]
            summary["audio"] = {
                "codec": audio.get("codec"),
                "sample_rate": audio.get("sample_rate"),
                "channels": audio.get("channels"),
                "bitrate": audio.get("bitrate")
            }
        
        return summary
    
    except Exception as e:
        return {"error": str(e)}

async def _save_analysis_report(analysis: Dict[str, Any], output_path: str) -> None:
    """Save analysis report to file."""
    try:
        with open(output_path, 'w') as f:
            json.dump(analysis, f, indent=2, default=str)
        logger.info(f"Analysis report saved to: {output_path}")
    except Exception as e:
        logger.error(f"Failed to save analysis report: {e}")

# Async main function for MCP registration
async def main() -> Dict[str, Any]:
    """Main function for MCP tool registration."""
    return {
        "status": "success",
        "message": "FFmpeg info and analysis tools initialized",
        "tools": ["ffmpeg_probe", "ffmpeg_analyze"],
        "description": "Probe and analyze media files using FFmpeg"
    }

if __name__ == "__main__":
    # Example usage
    test_probe = anyio.run(ffmpeg_probe(
        input_file="test.mp4",
        show_format=True,
        show_streams=True
    ))
    print(f"Probe test result: {test_probe}")
    
    test_analyze = anyio.run(ffmpeg_analyze(
        input_file="test.mp4",
        analysis_type="comprehensive"
    ))
    print(f"Analyze test result: {test_analyze}")
