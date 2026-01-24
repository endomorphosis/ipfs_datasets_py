# ipfs_datasets_py/mcp_server/tools/media_tools/ffmpeg_convert.py
"""
FFmpeg media conversion tool for the MCP server.

This tool provides comprehensive media format conversion capabilities using FFmpeg,
supporting video, audio, and container format transformations.
"""
import anyio
from typing import Dict, Any, Optional, Union, List
from pathlib import Path

from ipfs_datasets_py.mcp_server.logger import logger
from .ffmpeg_utils import ffmpeg_utils, FFmpegError

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
    timeout: int = 600
) -> Dict[str, Any]:
    """
    Convert media files between different formats using FFmpeg.
    
    This tool supports comprehensive media conversion including:
    - Video format conversion (MP4, AVI, MOV, MKV, etc.)
    - Audio format conversion (MP3, AAC, FLAC, WAV, etc.)
    - Codec transcoding (H.264, H.265, VP9, etc.)
    - Quality and compression settings
    - Resolution and frame rate changes
    
    Args:
        input_file: Input media file path or dataset containing file paths
        output_file: Output file path
        output_format: Output format (mp4, avi, mov, mkv, mp3, etc.)
        video_codec: Video codec (libx264, libx265, libvpx-vp9, etc.)
        audio_codec: Audio codec (aac, mp3, libflac, pcm_s16le, etc.)
        video_bitrate: Video bitrate (e.g., '1000k', '2M')
        audio_bitrate: Audio bitrate (e.g., '128k', '320k')
        resolution: Output resolution (e.g., '1920x1080', '1280x720')
        framerate: Output frame rate (e.g., '30', '60', '23.976')
        quality: Quality setting (e.g., 'high', 'medium', 'low' or CRF value)
        preset: Encoding preset (ultrafast, fast, medium, slow, veryslow)
        custom_args: Additional custom FFmpeg arguments
        timeout: Processing timeout in seconds
        
    Returns:
        Dict containing conversion results and metadata
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
                    "error": "Dataset input must contain 'file_path' or 'path' field",
                    "input": input_file
                }
        else:
            input_path = str(input_file)
        
        # Validate input file
        if not ffmpeg_utils.validate_input_file(input_path):
            return {
                "status": "error",
                "error": f"Input file not found or not accessible: {input_path}",
                "input_file": input_path
            }
        
        # Validate output path
        if not ffmpeg_utils.validate_output_path(output_file):
            return {
                "status": "error",
                "error": f"Output path not writable: {output_file}",
                "output_file": output_file
            }
        
        # Get input media info
        input_info = await ffmpeg_utils.probe_media_info(input_path)
        if input_info["status"] != "success":
            return {
                "status": "error",
                "error": f"Could not probe input file: {input_info.get('error', 'Unknown error')}",
                "input_file": input_path
            }
        
        # Build FFmpeg arguments
        args = []
        
        # Input file
        args.extend(["-i", input_path])
        
        # Video codec
        if video_codec:
            args.extend(["-c:v", video_codec])
        elif output_format in ['mp3', 'wav', 'flac', 'aac']:
            # Audio-only formats
            args.extend(["-vn"])  # No video
        
        # Audio codec
        if audio_codec:
            args.extend(["-c:a", audio_codec])
        
        # Quality settings
        if quality:
            if quality.lower() == "high":
                if video_codec in ['libx264', 'libx265']:
                    args.extend(["-crf", "18"])
                else:
                    args.extend(["-q:v", "2"])
            elif quality.lower() == "medium":
                if video_codec in ['libx264', 'libx265']:
                    args.extend(["-crf", "23"])
                else:
                    args.extend(["-q:v", "5"])
            elif quality.lower() == "low":
                if video_codec in ['libx264', 'libx265']:
                    args.extend(["-crf", "28"])
                else:
                    args.extend(["-q:v", "8"])
            elif quality.isdigit():
                # CRF value
                args.extend(["-crf", quality])
        
        # Preset
        if preset and video_codec in ['libx264', 'libx265']:
            args.extend(["-preset", preset])
        
        # Video bitrate
        if video_bitrate:
            args.extend(["-b:v", video_bitrate])
        
        # Audio bitrate
        if audio_bitrate:
            args.extend(["-b:a", audio_bitrate])
        
        # Resolution
        if resolution:
            args.extend(["-s", resolution])
        
        # Frame rate
        if framerate:
            args.extend(["-r", framerate])
        
        # Output format
        if output_format:
            args.extend(["-f", output_format])
        
        # Custom arguments
        if custom_args:
            args.extend(custom_args)
        
        # Overwrite output file
        args.append("-y")
        
        # Output file
        args.append(output_file)
        
        # Execute conversion
        logger.info(f"Starting conversion: {input_path} -> {output_file}")
        result = await ffmpeg_utils.run_ffmpeg_command(args, timeout=timeout)
        
        if result["status"] == "success":
            # Get output file info
            output_info = await ffmpeg_utils.probe_media_info(output_file)
            
            # Calculate file sizes
            input_size = Path(input_path).stat().st_size
            output_size = Path(output_file).stat().st_size if Path(output_file).exists() else 0
            
            return {
                "status": "success",
                "message": "Media conversion completed successfully",
                "input_file": input_path,
                "output_file": output_file,
                "input_info": input_info,
                "output_info": output_info,
                "conversion_stats": {
                    "input_size_bytes": input_size,
                    "output_size_bytes": output_size,
                    "compression_ratio": round(output_size / input_size, 3) if input_size > 0 else 0,
                    "size_reduction_percent": round((1 - output_size / input_size) * 100, 2) if input_size > 0 else 0
                },
                "ffmpeg_output": result.get("stderr", ""),
                "command": result.get("command", "")
            }
        else:
            return {
                "status": "error",
                "error": "FFmpeg conversion failed",
                "input_file": input_path,
                "output_file": output_file,
                "ffmpeg_error": result.get("stderr", ""),
                "ffmpeg_output": result.get("stdout", ""),
                "command": result.get("command", ""),
                "returncode": result.get("returncode", -1)
            }
    
    except FFmpegError as e:
        return {
            "status": "error",
            "error": f"FFmpeg error: {str(e)}",
            "input_file": input_file,
            "output_file": output_file
        }
    except Exception as e:
        logger.error(f"Error in ffmpeg_convert: {e}")
        return {
            "status": "error",
            "error": str(e),
            "input_file": input_file,
            "output_file": output_file
        }

# Async main function for MCP registration
async def main() -> Dict[str, Any]:
    """Main function for MCP tool registration."""
    return {
        "status": "success",
        "message": "FFmpeg conversion tool initialized",
        "tool": "ffmpeg_convert",
        "description": "Convert media files between different formats using FFmpeg",
        "supported_formats": ffmpeg_utils.get_supported_formats(),
        "supported_codecs": ffmpeg_utils.get_supported_codecs()
    }

if __name__ == "__main__":
    # Example usage
    test_result = anyio.run(ffmpeg_convert(
        input_file="input.mp4",
        output_file="output.mp4",
        video_codec="libx264",
        audio_codec="aac",
        quality="medium"
    ))
    print(f"Test result: {test_result}")
