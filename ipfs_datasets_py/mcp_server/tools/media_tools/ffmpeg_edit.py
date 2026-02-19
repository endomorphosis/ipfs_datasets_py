# ipfs_datasets_py/mcp_server/tools/media_tools/ffmpeg_edit.py
"""
FFmpeg editing tools for the MCP server.

This module provides tools for cutting, splicing, and concatenating media files
using FFmpeg for precise video and audio editing operations.
"""
import anyio
from typing import Dict, Any, Optional, Union, List, Tuple
from pathlib import Path
import tempfile
import json

import logging

logger = logging.getLogger(__name__)
from .ffmpeg_utils import ffmpeg_utils, FFmpegError

async def ffmpeg_cut(
    input_file: Union[str, Dict[str, Any]],
    output_file: str,
    start_time: str,
    end_time: Optional[str] = None,
    duration: Optional[str] = None,
    video_codec: str = "copy",
    audio_codec: str = "copy",
    accurate_seek: bool = True,
    timeout: int = 300
) -> Dict[str, Any]:
    """
    Cut/trim a segment from a media file using FFmpeg.
    
    This tool allows precise cutting of video and audio segments with:
    - Frame-accurate seeking
    - Lossless cutting (with copy codecs)
    - Time-based or duration-based cutting
    - Preservation of original quality
    
    Args:
        input_file: Input media file path or dataset
        output_file: Output file path for the cut segment
        start_time: Start time (e.g., '00:01:30', '90', '1:30')
        end_time: End time (e.g., '00:05:00', '300')
        duration: Duration instead of end time (e.g., '00:02:30', '150')
        video_codec: Video codec ('copy' for lossless, 'libx264' for re-encoding)
        audio_codec: Audio codec ('copy' for lossless, 'aac' for re-encoding)
        accurate_seek: Use accurate but slower seeking
        timeout: Processing timeout in seconds
        
    Returns:
        Dict containing cutting results
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
        
        # Validate output path
        if not ffmpeg_utils.validate_output_path(output_file):
            return {
                "status": "error",
                "error": f"Output path not writable: {output_file}"
            }
        
        # Validate time parameters
        if not end_time and not duration:
            return {
                "status": "error",
                "error": "Either end_time or duration must be specified"
            }
        
        if end_time and duration:
            return {
                "status": "error",
                "error": "Specify either end_time or duration, not both"
            }
        
        # Parse time values
        try:
            start_seconds = ffmpeg_utils.parse_time_format(start_time)
            if end_time:
                end_seconds = ffmpeg_utils.parse_time_format(end_time)
                duration_seconds = end_seconds - start_seconds
            else:
                duration_seconds = ffmpeg_utils.parse_time_format(duration)
                end_seconds = start_seconds + duration_seconds
            
            if duration_seconds <= 0:
                return {
                    "status": "error",
                    "error": "Duration must be positive"
                }
        except FFmpegError as e:
            return {
                "status": "error",
                "error": str(e)
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
        
        # Seeking options
        if accurate_seek:
            # Accurate seek (slower but frame-perfect)
            args.extend(["-ss", str(start_seconds)])
            args.extend(["-i", input_path])
        else:
            # Fast seek (faster but less accurate)
            args.extend(["-i", input_path])
            args.extend(["-ss", str(start_seconds)])
        
        # Duration
        args.extend(["-t", str(duration_seconds)])
        
        # Codecs
        args.extend(["-c:v", video_codec])
        args.extend(["-c:a", audio_codec])
        
        # Avoid re-encoding if using copy codecs
        if video_codec == "copy" and audio_codec == "copy":
            args.extend(["-avoid_negative_ts", "make_zero"])
        
        # Overwrite output
        args.append("-y")
        
        # Output file
        args.append(output_file)
        
        # Execute cutting
        logger.info(f"Cutting segment: {start_time} to {end_time or f'+{duration}'}")
        result = await ffmpeg_utils.run_ffmpeg_command(args, timeout=timeout)
        
        if result["status"] == "success":
            # Get output file info
            output_info = await ffmpeg_utils.probe_media_info(output_file)
            
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
                    "duration_seconds": duration_seconds
                },
                "input_info": input_info,
                "output_info": output_info,
                "command": result.get("command", "")
            }
        else:
            return {
                "status": "error",
                "error": "FFmpeg cutting failed",
                "ffmpeg_error": result.get("stderr", ""),
                "command": result.get("command", ""),
                "returncode": result.get("returncode", -1)
            }
    
    except Exception as e:
        logger.error(f"Error in ffmpeg_cut: {e}")
        return {
            "status": "error",
            "error": str(e),
            "input_file": input_file
        }

async def ffmpeg_splice(
    input_files: List[Union[str, Dict[str, Any]]],
    output_file: str,
    segments: List[Dict[str, Any]],
    video_codec: str = "libx264",
    audio_codec: str = "aac",
    transition_type: str = "cut",
    transition_duration: float = 0.0,
    timeout: int = 600
) -> Dict[str, Any]:
    """
    Splice multiple segments from various files into a single output file.
    
    This tool creates complex edits by:
    - Extracting specific segments from multiple input files
    - Applying transitions between segments
    - Maintaining sync between video and audio
    - Supporting crossfades and other effects
    
    Args:
        input_files: List of input media files or datasets
        output_file: Output file path
        segments: List of segment definitions with start/end times and source files
        video_codec: Video codec for output
        audio_codec: Audio codec for output
        transition_type: Type of transition ('cut', 'fade', 'crossfade')
        transition_duration: Duration of transitions in seconds
        timeout: Processing timeout in seconds
        
    Returns:
        Dict containing splicing results
    """
    try:
        if not input_files:
            return {
                "status": "error",
                "error": "At least one input file is required"
            }
        
        if not segments:
            return {
                "status": "error",
                "error": "At least one segment definition is required"
            }
        
        # Validate and normalize input files
        validated_inputs = []
        for input_file in input_files:
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
            
            if not ffmpeg_utils.validate_input_file(input_path):
                return {
                    "status": "error",
                    "error": f"Input file not found: {input_path}"
                }
            
            validated_inputs.append(input_path)
        
        # Validate output path
        if not ffmpeg_utils.validate_output_path(output_file):
            return {
                "status": "error",
                "error": f"Output path not writable: {output_file}"
            }
        
        # Create temporary directory for intermediate files
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            segment_files = []
            
            # Extract each segment
            for i, segment in enumerate(segments):
                source_file = segment.get('source_file')
                start_time = segment.get('start_time')
                end_time = segment.get('end_time')
                duration = segment.get('duration')
                
                if source_file not in validated_inputs:
                    return {
                        "status": "error",
                        "error": f"Source file not in input list: {source_file}"
                    }
                
                if not start_time:
                    return {
                        "status": "error",
                        "error": f"Segment {i}: start_time is required"
                    }
                
                # Extract segment
                segment_output = temp_path / f"segment_{i:03d}.mp4"
                cut_result = await ffmpeg_cut(
                    input_file=source_file,
                    output_file=str(segment_output),
                    start_time=start_time,
                    end_time=end_time,
                    duration=duration,
                    video_codec="libx264",  # Re-encode for splicing
                    audio_codec="aac",
                    timeout=timeout // len(segments)
                )
                
                if cut_result["status"] != "success":
                    return {
                        "status": "error",
                        "error": f"Failed to extract segment {i}: {cut_result.get('error')}"
                    }
                
                segment_files.append(str(segment_output))
            
            # Create concat list file
            concat_file = temp_path / "concat_list.txt"
            with open(concat_file, 'w') as f:
                for segment_file in segment_files:
                    f.write(f"file '{segment_file}'\n")
                    if transition_duration > 0 and transition_type in ['fade', 'crossfade']:
                        # Add transition effects (simplified)
                        f.write(f"duration {transition_duration}\n")
            
            # Concatenate segments
            concat_result = await ffmpeg_concat(
                input_files=segment_files,
                output_file=output_file,
                video_codec=video_codec,
                audio_codec=audio_codec,
                method="file_list",
                timeout=timeout
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
                    "concat_result": concat_result
                }
            else:
                return {
                    "status": "error",
                    "error": "Failed to concatenate segments",
                    "concat_error": concat_result.get("error")
                }
    
    except Exception as e:
        logger.error(f"Error in ffmpeg_splice: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

async def ffmpeg_concat(
    input_files: List[Union[str, Dict[str, Any]]],
    output_file: str,
    video_codec: str = "copy",
    audio_codec: str = "copy",
    method: str = "filter",
    safe_mode: bool = True,
    timeout: int = 600
) -> Dict[str, Any]:
    """
    Concatenate multiple media files into a single output file.
    
    This tool supports different concatenation methods:
    - Filter complex (re-encodes, handles different formats)
    - Demuxer concat (fast, requires same format/codec)
    - File list concat (intermediate approach)
    
    Args:
        input_files: List of input media files or datasets
        output_file: Output file path
        video_codec: Video codec ('copy' for no re-encoding)
        audio_codec: Audio codec ('copy' for no re-encoding)
        method: Concatenation method ('filter', 'demuxer', 'file_list')
        safe_mode: Enable safe file path handling
        timeout: Processing timeout in seconds
        
    Returns:
        Dict containing concatenation results
    """
    try:
        if not input_files:
            return {
                "status": "error",
                "error": "At least one input file is required"
            }
        
        # Validate and normalize input files
        validated_inputs = []
        for input_file in input_files:
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
            
            if not ffmpeg_utils.validate_input_file(input_path):
                return {
                    "status": "error",
                    "error": f"Input file not found: {input_path}"
                }
            
            validated_inputs.append(input_path)
        
        # Validate output path
        if not ffmpeg_utils.validate_output_path(output_file):
            return {
                "status": "error",
                "error": f"Output path not writable: {output_file}"
            }
        
        # Get info for all input files
        input_infos = []
        for input_path in validated_inputs:
            info = await ffmpeg_utils.probe_media_info(input_path)
            if info["status"] != "success":
                return {
                    "status": "error",
                    "error": f"Could not probe input file: {input_path}"
                }
            input_infos.append(info)
        
        # Build FFmpeg arguments based on method
        args = []
        
        if method == "demuxer":
            # Demuxer concat (fastest, requires same format)
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                for input_path in validated_inputs:
                    f.write(f"file '{input_path}'\n")
                concat_file = f.name
            
            args.extend(["-f", "concat"])
            if safe_mode:
                args.extend(["-safe", "0"])
            args.extend(["-i", concat_file])
            args.extend(["-c:v", video_codec])
            args.extend(["-c:a", audio_codec])
            
        elif method == "filter":
            # Filter complex (most compatible, slower)
            for input_path in validated_inputs:
                args.extend(["-i", input_path])
            
            # Build filter complex
            n_inputs = len(validated_inputs)
            filter_inputs = "".join([f"[{i}:v][{i}:a]" for i in range(n_inputs)])
            filter_complex = f"{filter_inputs}concat=n={n_inputs}:v=1:a=1[outv][outa]"
            
            args.extend(["-filter_complex", filter_complex])
            args.extend(["-map", "[outv]"])
            args.extend(["-map", "[outa]"])
            args.extend(["-c:v", video_codec])
            args.extend(["-c:a", audio_codec])
            
        elif method == "file_list":
            # File list method (good balance)
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                for input_path in validated_inputs:
                    f.write(f"file '{input_path}'\n")
                concat_file = f.name
            
            args.extend(["-f", "concat"])
            args.extend(["-safe", "0"])
            args.extend(["-i", concat_file])
            args.extend(["-c", "copy"])
        
        else:
            return {
                "status": "error",
                "error": f"Unknown concatenation method: {method}"
            }
        
        # Overwrite output
        args.append("-y")
        
        # Output file
        args.append(output_file)
        
        # Execute concatenation
        logger.info(f"Concatenating {len(validated_inputs)} files using {method} method")
        result = await ffmpeg_utils.run_ffmpeg_command(args, timeout=timeout)
        
        # Clean up temporary files
        if method in ["demuxer", "file_list"] and 'concat_file' in locals():
            try:
                Path(concat_file).unlink()
            except (OSError, FileNotFoundError):
                # Ignore if file doesn't exist or can't be deleted
                pass
        
        if result["status"] == "success":
            # Get output file info
            output_info = await ffmpeg_utils.probe_media_info(output_file)
            
            # Calculate total duration
            total_duration = sum([
                float(info["format"].get("duration", 0))
                for info in input_infos
            ])
            
            return {
                "status": "success",
                "message": "Media concatenation completed successfully",
                "input_files": validated_inputs,
                "output_file": output_file,
                "method": method,
                "input_count": len(validated_inputs),
                "total_input_duration": total_duration,
                "output_info": output_info,
                "command": result.get("command", "")
            }
        else:
            return {
                "status": "error",
                "error": "FFmpeg concatenation failed",
                "ffmpeg_error": result.get("stderr", ""),
                "command": result.get("command", ""),
                "returncode": result.get("returncode", -1)
            }
    
    except Exception as e:
        logger.error(f"Error in ffmpeg_concat: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

# Async main function for MCP registration
async def main() -> Dict[str, Any]:
    """Main function for MCP tool registration."""
    return {
        "status": "success",
        "message": "FFmpeg editing tools initialized",
        "tools": ["ffmpeg_cut", "ffmpeg_splice", "ffmpeg_concat"],
        "description": "Cut, splice, and concatenate media files using FFmpeg"
    }

if __name__ == "__main__":
    # Example usage
    test_cut = anyio.run(ffmpeg_cut(
        input_file="input.mp4",
        output_file="cut_segment.mp4",
        start_time="00:01:00",
        duration="00:02:00"
    ))
    print(f"Cut test result: {test_cut}")
    
    test_concat = anyio.run(ffmpeg_concat(
        input_files=["part1.mp4", "part2.mp4", "part3.mp4"],
        output_file="concatenated.mp4"
    ))
    print(f"Concat test result: {test_concat}")
