# ipfs_datasets_py/mcp_server/tools/media_tools/ffmpeg_stream.py
"""
FFmpeg streaming tools for the MCP server.

This module provides tools for streaming media input and output using FFmpeg,
supporting various streaming protocols and formats.
"""
import anyio
from typing import Dict, Any, Optional, Union, List
from pathlib import Path

import logging

logger = logging.getLogger(__name__)
from .ffmpeg_utils import ffmpeg_utils, FFmpegError

async def ffmpeg_stream_input(
    stream_url: str,
    output_file: str,
    duration: Optional[str] = None,
    video_codec: str = "copy",
    audio_codec: str = "copy",
    format: Optional[str] = None,
    buffer_size: Optional[str] = None,
    timeout: int = 3600
) -> Dict[str, Any]:
    """
    Capture/ingest media from streaming sources using FFmpeg.
    
    This tool supports:
    - RTMP/RTMPS streams
    - HTTP/HTTPS streams
    - UDP/RTP streams
    - WebRTC streams
    - Network cameras (IP cameras)
    - Screen capture
    
    Args:
        stream_url: Input stream URL or source
        output_file: Output file path to save the stream
        duration: Recording duration (e.g., '00:10:00' for 10 minutes)
        video_codec: Video codec for encoding ('copy' to avoid re-encoding)
        audio_codec: Audio codec for encoding ('copy' to avoid re-encoding)
        format: Input format hint (optional)
        buffer_size: Input buffer size (e.g., '1M', '512k')
        timeout: Maximum recording timeout in seconds
        
    Returns:
        Dict containing stream capture results
    """
    try:
        # Validate output path
        if not ffmpeg_utils.validate_output_path(output_file):
            return {
                "status": "error",
                "error": f"Output path not writable: {output_file}"
            }
        
        # Build FFmpeg arguments
        args = []
        
        # Input buffer size
        if buffer_size:
            args.extend(["-buffer_size", buffer_size])
        
        # Input format
        if format:
            args.extend(["-f", format])
        
        # Input stream
        args.extend(["-i", stream_url])
        
        # Duration limit
        if duration:
            try:
                duration_seconds = ffmpeg_utils.parse_time_format(duration)
                args.extend(["-t", str(duration_seconds)])
            except FFmpegError as e:
                return {
                    "status": "error",
                    "error": f"Invalid duration format: {e}"
                }
        
        # Codecs
        args.extend(["-c:v", video_codec])
        args.extend(["-c:a", audio_codec])
        
        # Overwrite output
        args.append("-y")
        
        # Output file
        args.append(output_file)
        
        # Execute stream capture
        logger.info(f"Starting stream capture: {stream_url} -> {output_file}")
        result = await ffmpeg_utils.run_ffmpeg_command(args, timeout=timeout, capture_output=False)
        
        if result["status"] == "success":
            # Get output file info if it exists
            output_info = None
            if Path(output_file).exists():
                output_info = await ffmpeg_utils.probe_media_info(output_file)
            
            return {
                "status": "success",
                "message": "Stream capture completed successfully",
                "stream_url": stream_url,
                "output_file": output_file,
                "output_info": output_info,
                "duration_requested": duration,
                "command": result.get("command", "")
            }
        else:
            return {
                "status": "error",
                "error": "FFmpeg stream capture failed",
                "stream_url": stream_url,
                "ffmpeg_error": result.get("stderr", ""),
                "command": result.get("command", ""),
                "returncode": result.get("returncode", -1)
            }
    
    except Exception as e:
        logger.error(f"Error in ffmpeg_stream_input: {e}")
        return {
            "status": "error",
            "error": str(e),
            "stream_url": stream_url,
            "output_file": output_file
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
    timeout: int = 3600
) -> Dict[str, Any]:
    """
    Stream media to output destinations using FFmpeg.
    
    This tool supports streaming to:
    - RTMP servers (YouTube, Twitch, Facebook Live, etc.)
    - RTSP servers
    - UDP/RTP destinations
    - HTTP/HLS endpoints
    - Custom streaming protocols
    
    Args:
        input_file: Input media file path or dataset
        stream_url: Output stream URL or destination
        video_codec: Video codec for streaming
        audio_codec: Audio codec for streaming
        video_bitrate: Video bitrate (e.g., '2500k', '5M')
        audio_bitrate: Audio bitrate (e.g., '128k', '320k')
        resolution: Output resolution (e.g., '1920x1080')
        framerate: Output frame rate (e.g., '30', '60')
        format: Output format (flv, mpegts, etc.)
        preset: Encoding preset for quality/speed balance
        tune: Encoding tune (film, animation, zerolatency)
        keyframe_interval: Keyframe interval in seconds
        buffer_size: Output buffer size
        max_muxing_queue_size: Maximum muxing queue size
        timeout: Streaming timeout in seconds
        
    Returns:
        Dict containing streaming results
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
        
        # Get input media info
        input_info = await ffmpeg_utils.probe_media_info(input_path)
        if input_info["status"] != "success":
            return {
                "status": "error",
                "error": f"Could not probe input file: {input_info.get('error')}"
            }
        
        # Build FFmpeg arguments
        args = []
        
        # Input file
        args.extend(["-re", "-i", input_path])  # -re for realtime reading
        
        # Video codec and settings
        args.extend(["-c:v", video_codec])
        
        if video_bitrate:
            args.extend(["-b:v", video_bitrate])
        
        if resolution:
            args.extend(["-s", resolution])
        
        if framerate:
            args.extend(["-r", framerate])
        
        # Preset and tune for H.264/H.265
        if video_codec in ['libx264', 'libx265']:
            args.extend(["-preset", preset])
            if tune:
                args.extend(["-tune", tune])
        
        # Keyframe interval
        if keyframe_interval:
            args.extend(["-g", str(int(float(keyframe_interval) * float(framerate or "30")))])
        
        # Audio codec and settings
        args.extend(["-c:a", audio_codec])
        
        if audio_bitrate:
            args.extend(["-b:a", audio_bitrate])
        
        # Buffer settings
        if buffer_size:
            args.extend(["-bufsize", buffer_size])
        
        args.extend(["-max_muxing_queue_size", max_muxing_queue_size])
        
        # Output format
        args.extend(["-f", format])
        
        # Stream URL
        args.append(stream_url)
        
        # Execute streaming
        logger.info(f"Starting streaming: {input_path} -> {stream_url}")
        result = await ffmpeg_utils.run_ffmpeg_command(args, timeout=timeout, capture_output=False)
        
        if result["status"] == "success":
            return {
                "status": "success",
                "message": "Streaming completed successfully",
                "input_file": input_path,
                "stream_url": stream_url,
                "input_info": input_info,
                "streaming_settings": {
                    "video_codec": video_codec,
                    "audio_codec": audio_codec,
                    "video_bitrate": video_bitrate,
                    "audio_bitrate": audio_bitrate,
                    "resolution": resolution,
                    "framerate": framerate,
                    "format": format
                },
                "command": result.get("command", "")
            }
        else:
            return {
                "status": "error",
                "error": "FFmpeg streaming failed",
                "input_file": input_path,
                "stream_url": stream_url,
                "ffmpeg_error": result.get("stderr", ""),
                "command": result.get("command", ""),
                "returncode": result.get("returncode", -1)
            }
    
    except Exception as e:
        logger.error(f"Error in ffmpeg_stream_output: {e}")
        return {
            "status": "error",
            "error": str(e),
            "input_file": input_file,
            "stream_url": stream_url
        }

# Async main function for MCP registration
async def main() -> Dict[str, Any]:
    """Main function for MCP tool registration."""
    return {
        "status": "success",
        "message": "FFmpeg streaming tools initialized",
        "tools": ["ffmpeg_stream_input", "ffmpeg_stream_output"],
        "description": "Stream media input and output using FFmpeg",
        "supported_protocols": [
            "rtmp", "rtmps", "http", "https", "udp", "rtp", "rtsp",
            "hls", "dash", "webrtc", "srt"
        ]
    }

if __name__ == "__main__":
    # Example usage
    test_input = anyio.run(ffmpeg_stream_input(
        stream_url="rtmp://example.com/live/stream",
        output_file="captured_stream.mp4",
        duration="00:05:00"
    ))
    print(f"Stream input test result: {test_input}")
    
    test_output = anyio.run(ffmpeg_stream_output(
        input_file="input.mp4",
        stream_url="rtmp://youtube.com/live/YOUR_STREAM_KEY",
        video_bitrate="2500k",
        audio_bitrate="128k"
    ))
    print(f"Stream output test result: {test_output}")
