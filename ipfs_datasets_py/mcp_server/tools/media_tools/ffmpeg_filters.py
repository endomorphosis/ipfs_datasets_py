# ipfs_datasets_py/mcp_server/tools/media_tools/ffmpeg_filters.py
"""
FFmpeg filters tool for the MCP server.

This tool provides comprehensive audio and video filter application capabilities using FFmpeg,
supporting complex filter graphs, real-time effects, and filter chain processing.
"""
import anyio
from typing import Dict, Any, Optional, Union, List
from pathlib import Path

import logging

logger = logging.getLogger(__name__)
from .ffmpeg_utils import ffmpeg_utils, FFmpegError

async def ffmpeg_apply_filters(
    input_file: Union[str, Dict[str, Any]],
    output_file: str,
    video_filters: Optional[List[str]] = None,
    audio_filters: Optional[List[str]] = None,
    filter_complex: Optional[str] = None,
    output_format: Optional[str] = None,
    preserve_metadata: bool = True,
    timeout: int = 600
) -> Dict[str, Any]:
    """
    Apply video and audio filters to media files using FFmpeg.
    
    This tool supports comprehensive filter application including:
    - Video filters (scale, crop, rotate, blur, sharpen, etc.)
    - Audio filters (volume, equalizer, noise reduction, etc.)
    - Complex filter graphs for advanced processing
    - Filter chains for sequential processing
    - Real-time filter preview and application
    
    Args:
        input_file: Input media file path or dataset containing file paths
        output_file: Output file path
        video_filters: List of video filter strings (e.g., ['scale=1280:720', 'blur=1'])
        audio_filters: List of audio filter strings (e.g., ['volume=0.5', 'highpass=f=200'])
        filter_complex: Complex filter graph string for advanced processing
        output_format: Output format (inferred from extension if not provided)
        preserve_metadata: Whether to preserve original metadata
        timeout: Maximum execution time in seconds
        
    Returns:
        Dict containing:
        - status: "success" or "error"
        - input_file: Path to input file
        - output_file: Path to output file
        - filters_applied: List of filters that were applied
        - duration: Processing duration in seconds
        - file_size_before: Input file size in bytes
        - file_size_after: Output file size in bytes
        - message: Success/error message
        - command: FFmpeg command used (for debugging)
    """
    try:
        # Handle different input types
        if isinstance(input_file, dict):
            # Extract file path from dataset
            if "file_path" in input_file:
                input_path = input_file["file_path"]
            elif "path" in input_file:
                input_path = input_file["path"]
            else:
                return {
                    "status": "error",
                    "error": "Invalid input: dataset must contain 'file_path' or 'path' field",
                    "input_file": input_file,
                    "output_file": output_file
                }
        else:
            input_path = str(input_file)
        
        # Validate input file
        if not ffmpeg_utils.validate_input_file(input_path):
            return {
                "status": "error",
                "error": f"Input file not found or not accessible: {input_path}",
                "input_file": input_path,
                "output_file": output_file
            }
        
        # Validate output path
        if not ffmpeg_utils.validate_output_path(output_file):
            return {
                "status": "error",
                "error": f"Output path not writable: {output_file}",
                "input_file": input_path,
                "output_file": output_file
            }
        
        # Get input file size
        input_size = Path(input_path).stat().st_size
        
        # Build FFmpeg command
        cmd = [ffmpeg_utils.ffmpeg_path, "-i", input_path]
        
        # Handle filter application
        filters_applied = []
        
        if filter_complex:
            # Use complex filter graph
            cmd.extend(["-filter_complex", filter_complex])
            filters_applied.append(f"complex: {filter_complex}")
        else:
            # Use simple filters
            if video_filters:
                video_filter_chain = ",".join(video_filters)
                cmd.extend(["-vf", video_filter_chain])
                filters_applied.extend([f"video: {vf}" for vf in video_filters])
            
            if audio_filters:
                audio_filter_chain = ",".join(audio_filters)
                cmd.extend(["-af", audio_filter_chain])
                filters_applied.extend([f"audio: {af}" for af in audio_filters])
        
        # Add output format if specified
        if output_format:
            cmd.extend(["-f", output_format])
        
        # Preserve metadata if requested
        if preserve_metadata:
            cmd.extend(["-map_metadata", "0"])
        
        # Add output file
        cmd.append(output_file)
        
        # Execute FFmpeg command
        logger.info(f"Applying filters with command: {' '.join(cmd)}")
        result = await ffmpeg_utils.run_ffmpeg_command(cmd, timeout=timeout)
        
        if result["returncode"] == 0:
            # Get output file size
            output_size = Path(output_file).stat().st_size if Path(output_file).exists() else 0
            
            return {
                "status": "success",
                "input_file": input_path,
                "output_file": output_file,
                "filters_applied": filters_applied,
                "duration": result["duration"],
                "file_size_before": input_size,
                "file_size_after": output_size,
                "compression_ratio": (input_size - output_size) / input_size if input_size > 0 else 0,
                "command": " ".join(cmd),
                "message": f"Successfully applied {len(filters_applied)} filters to media file"
            }
        else:
            return {
                "status": "error",
                "error": "FFmpeg filter application failed",
                "input_file": input_path,
                "output_file": output_file,
                "filters_applied": filters_applied,
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
        logger.error(f"Error in ffmpeg_apply_filters: {e}")
        return {
            "status": "error",
            "error": str(e),
            "input_file": input_file,
            "output_file": output_file
        }

async def get_available_filters() -> Dict[str, Any]:
    """
    Get list of available FFmpeg filters.
    
    Returns:
        Dict containing:
        - status: "success" or "error"
        - video_filters: List of available video filters
        - audio_filters: List of available audio filters
        - filter_count: Total number of filters
    """
    try:
        # Get available filters
        cmd = [ffmpeg_utils.ffmpeg_path, "-filters"]
        result = await ffmpeg_utils.run_ffmpeg_command(cmd, timeout=10)
        
        if result["returncode"] == 0:
            lines = result["stdout"].split('\n')
            video_filters = []
            audio_filters = []
            
            for line in lines:
                if line.strip() and not line.startswith('Filters:') and not line.startswith('---'):
                    parts = line.split()
                    if len(parts) >= 3:
                        flags = parts[0]
                        filter_name = parts[1]
                        
                        if 'V' in flags:  # Video filter
                            video_filters.append(filter_name)
                        if 'A' in flags:  # Audio filter
                            audio_filters.append(filter_name)
            
            return {
                "status": "success",
                "video_filters": video_filters,
                "audio_filters": audio_filters,
                "filter_count": len(video_filters) + len(audio_filters)
            }
        else:
            return {
                "status": "error",
                "error": "Failed to get available filters",
                "ffmpeg_error": result.get("stderr", "")
            }
    
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }

# Async main function for MCP registration
async def main() -> Dict[str, Any]:
    """Main function for MCP tool registration."""
    filters_info = await get_available_filters()
    
    return {
        "status": "success",
        "message": "FFmpeg filters tool initialized",
        "tool": "ffmpeg_apply_filters",
        "description": "Apply video and audio filters to media files using FFmpeg",
        "available_filters": filters_info.get("filter_count", 0),
        "capabilities": [
            "Video filter application",
            "Audio filter application", 
            "Complex filter graphs",
            "Filter chain processing",
            "Metadata preservation"
        ]
    }

if __name__ == "__main__":
    # Example usage
    test_result = anyio.run(ffmpeg_apply_filters(
        input_file="input.mp4",
        output_file="filtered_output.mp4",
        video_filters=["scale=1280:720", "brightness=0.1"],
        audio_filters=["volume=0.8"]
    ))
    print(f"Test result: {test_result}")
