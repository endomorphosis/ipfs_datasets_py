"""
FFmpeg Media Conversion Tool - MCP Wrapper

This module provides MCP tool interfaces for FFmpeg media conversion.
The core implementation is in ipfs_datasets_py.data_transformation.multimedia.ffmpeg_wrapper

All business logic should reside in the core module, and this file serves
as a thin wrapper to expose that functionality through the MCP interface.
"""

import anyio
from typing import Dict, Any, Optional, Union, List
from pathlib import Path
import logging

# Import from core multimedia module
from ipfs_datasets_py.data_transformation.multimedia import FFmpegWrapper

logger = logging.getLogger(__name__)

# Global wrapper instance for reuse
_ffmpeg_wrapper = None


def get_ffmpeg_wrapper() -> FFmpegWrapper:
    """Get or create the global FFmpegWrapper instance."""
    global _ffmpeg_wrapper
    if _ffmpeg_wrapper is None:
        _ffmpeg_wrapper = FFmpegWrapper(enable_logging=True)
    return _ffmpeg_wrapper


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
    
    This is a thin wrapper around the core FFmpegWrapper.convert_video method.
    
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
        # Get the core FFmpeg wrapper
        wrapper = get_ffmpeg_wrapper()
        
        # Check if FFmpeg is available
        if not wrapper.is_available():
            return {
                "status": "error",
                "success": False,
                "error": "FFmpeg is not available. Please install FFmpeg.",
                "input_file": str(input_file),
                "output_file": output_file
            }
        
        # Handle dataset input
        if isinstance(input_file, dict):
            if 'file_path' in input_file:
                input_path = input_file['file_path']
            elif 'path' in input_file:
                input_path = input_file['path']
            else:
                return {
                    "status": "error",
                    "success": False,
                    "error": "Dataset input must contain 'file_path' or 'path' field",
                    "input": input_file
                }
        else:
            input_path = str(input_file)
        
        # Validate input file exists
        input_file_path = Path(input_path)
        if not input_file_path.exists():
            return {
                "status": "error",
                "success": False,
                "error": f"Input file not found: {input_path}",
                "input_file": input_path,
                "output_file": output_file
            }
        
        # Build kwargs for the core wrapper
        conversion_kwargs = {}
        
        if output_format:
            conversion_kwargs['output_format'] = output_format
        if video_codec:
            conversion_kwargs['video_codec'] = video_codec
        if audio_codec:
            conversion_kwargs['audio_codec'] = audio_codec
        if video_bitrate:
            conversion_kwargs['video_bitrate'] = video_bitrate
        if audio_bitrate:
            conversion_kwargs['audio_bitrate'] = audio_bitrate
        if resolution:
            conversion_kwargs['resolution'] = resolution
        if framerate:
            conversion_kwargs['framerate'] = framerate
        if quality:
            conversion_kwargs['quality'] = quality
        if preset:
            conversion_kwargs['preset'] = preset
        if custom_args:
            conversion_kwargs['custom_args'] = custom_args
        if timeout:
            conversion_kwargs['timeout'] = timeout
        
        # Delegate to core FFmpegWrapper
        logger.info(f"Converting {input_path} to {output_file} using core FFmpegWrapper")
        result = await wrapper.convert_video(
            input_path=input_path,
            output_path=output_file,
            **conversion_kwargs
        )
        
        # Ensure standard response format
        if not isinstance(result, dict):
            result = {"status": "success", "result": result}
        
        # Add MCP-specific fields
        result["input_file"] = input_path
        result["output_file"] = output_file
        
        # Normalize status field
        if "success" in result:
            result["status"] = "success" if result["success"] else "error"
        elif "status" not in result:
            result["status"] = "success"
        
        return result
        
    except Exception as e:
        logger.error(f"FFmpeg conversion failed: {e}", exc_info=True)
        return {
            "status": "error",
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__,
            "input_file": str(input_file),
            "output_file": output_file
        }


async def ffmpeg_extract_audio(
    input_file: Union[str, Dict[str, Any]],
    output_file: str,
    audio_codec: Optional[str] = None,
    audio_bitrate: Optional[str] = None,
    sample_rate: Optional[str] = None
) -> Dict[str, Any]:
    """
    Extract audio from a media file.
    
    This is a thin wrapper around the core FFmpegWrapper.extract_audio method.
    
    Args:
        input_file: Input media file path
        output_file: Output audio file path
        audio_codec: Audio codec (mp3, aac, flac, etc.)
        audio_bitrate: Audio bitrate (e.g., '128k', '320k')
        sample_rate: Sample rate (e.g., '44100', '48000')
    
    Returns:
        Dict containing extraction results
    """
    try:
        wrapper = get_ffmpeg_wrapper()
        
        # Handle dataset input
        if isinstance(input_file, dict):
            input_path = input_file.get('file_path') or input_file.get('path')
        else:
            input_path = str(input_file)
        
        if not input_path:
            return {
                "status": "error",
                "error": "Invalid input file"
            }
        
        # Build kwargs
        kwargs = {}
        if audio_codec:
            kwargs['audio_codec'] = audio_codec
        if audio_bitrate:
            kwargs['audio_bitrate'] = audio_bitrate
        if sample_rate:
            kwargs['sample_rate'] = sample_rate
        
        # Delegate to core
        result = await wrapper.extract_audio(
            input_path=input_path,
            output_path=output_file,
            **kwargs
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Audio extraction failed: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


async def ffmpeg_analyze(
    input_file: Union[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Analyze media file and extract metadata.
    
    This is a thin wrapper around the core FFmpegWrapper.analyze_media method.
    
    Args:
        input_file: Input media file path
    
    Returns:
        Dict containing media analysis results
    """
    try:
        wrapper = get_ffmpeg_wrapper()
        
        # Handle dataset input
        if isinstance(input_file, dict):
            input_path = input_file.get('file_path') or input_file.get('path')
        else:
            input_path = str(input_file)
        
        if not input_path:
            return {
                "status": "error",
                "error": "Invalid input file"
            }
        
        # Delegate to core
        result = await wrapper.analyze_media(input_path=input_path)
        
        return result
        
    except Exception as e:
        logger.error(f"Media analysis failed: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


# Legacy compatibility - map old function names
ffmpeg_info = ffmpeg_analyze
