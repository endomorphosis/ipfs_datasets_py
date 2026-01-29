# ipfs_datasets_py/mcp_server/tools/media_tools/ffmpeg_mux_demux.py
"""
FFmpeg muxing and demuxing tools for the MCP server.

This module provides tools for combining (muxing) and separating (demuxing)
audio and video streams in media containers.
"""
import anyio
from typing import Dict, Any, Optional, Union, List
from pathlib import Path

import logging

logger = logging.getLogger(__name__)
from .ffmpeg_utils import ffmpeg_utils, FFmpegError

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
    timeout: int = 300
) -> Dict[str, Any]:
    """
    Mux (combine) separate video, audio, and subtitle streams into a single container.
    
    This tool allows combining:
    - Video stream from one file
    - Multiple audio streams (different languages, commentary tracks)
    - Multiple subtitle streams
    - Custom stream mapping and metadata
    
    Args:
        video_input: Path to video file
        audio_inputs: List of paths to audio files
        subtitle_inputs: List of paths to subtitle files
        output_file: Output file path
        output_format: Output container format
        video_codec: Video codec ('copy' to avoid re-encoding)
        audio_codec: Audio codec ('copy' to avoid re-encoding)
        subtitle_codec: Subtitle codec ('copy' to avoid re-encoding)
        map_streams: Custom stream mapping (e.g., ['0:v:0', '1:a:0'])
        metadata: Metadata to add to output file
        timeout: Processing timeout in seconds
        
    Returns:
        Dict containing muxing results
    """
    try:
        if not output_file:
            return {
                "status": "error",
                "error": "Output file path is required"
            }
        
        # Validate inputs
        inputs = []
        if video_input:
            if not ffmpeg_utils.validate_input_file(video_input):
                return {
                    "status": "error",
                    "error": f"Video input file not found: {video_input}"
                }
            inputs.append(video_input)
        
        if audio_inputs:
            for audio_file in audio_inputs:
                if not ffmpeg_utils.validate_input_file(audio_file):
                    return {
                        "status": "error",
                        "error": f"Audio input file not found: {audio_file}"
                    }
                inputs.append(audio_file)
        
        if subtitle_inputs:
            for subtitle_file in subtitle_inputs:
                if not ffmpeg_utils.validate_input_file(subtitle_file):
                    return {
                        "status": "error",
                        "error": f"Subtitle input file not found: {subtitle_file}"
                    }
                inputs.append(subtitle_file)
        
        if not inputs:
            return {
                "status": "error",
                "error": "At least one input file is required"
            }
        
        # Validate output path
        if not ffmpeg_utils.validate_output_path(output_file):
            return {
                "status": "error",
                "error": f"Output path not writable: {output_file}"
            }
        
        # Build FFmpeg arguments
        args = []
        
        # Add all input files
        for input_file in inputs:
            args.extend(["-i", input_file])
        
        # Stream mapping
        if map_streams:
            for mapping in map_streams:
                args.extend(["-map", mapping])
        else:
            # Default mapping: include all streams
            if video_input:
                args.extend(["-map", "0:v"])  # Video from first input
            
            # Map audio streams
            audio_start_idx = 1 if video_input else 0
            if audio_inputs:
                for i, _ in enumerate(audio_inputs):
                    args.extend(["-map", f"{audio_start_idx + i}:a"])
            
            # Map subtitle streams
            subtitle_start_idx = audio_start_idx + (len(audio_inputs) if audio_inputs else 0)
            if subtitle_inputs:
                for i, _ in enumerate(subtitle_inputs):
                    args.extend(["-map", f"{subtitle_start_idx + i}:s"])
        
        # Codecs
        args.extend(["-c:v", video_codec])
        args.extend(["-c:a", audio_codec])
        if subtitle_inputs:
            args.extend(["-c:s", subtitle_codec])
        
        # Metadata
        if metadata:
            for key, value in metadata.items():
                args.extend(["-metadata", f"{key}={value}"])
        
        # Output format
        if output_format:
            args.extend(["-f", output_format])
        
        # Overwrite output
        args.append("-y")
        
        # Output file
        args.append(output_file)
        
        # Execute muxing
        logger.info(f"Starting muxing to: {output_file}")
        result = await ffmpeg_utils.run_ffmpeg_command(args, timeout=timeout)
        
        if result["status"] == "success":
            # Get output file info
            output_info = await ffmpeg_utils.probe_media_info(output_file)
            
            return {
                "status": "success",
                "message": "Media muxing completed successfully",
                "inputs": {
                    "video": video_input,
                    "audio": audio_inputs,
                    "subtitle": subtitle_inputs
                },
                "output_file": output_file,
                "output_info": output_info,
                "command": result.get("command", "")
            }
        else:
            return {
                "status": "error",
                "error": "FFmpeg muxing failed",
                "ffmpeg_error": result.get("stderr", ""),
                "command": result.get("command", ""),
                "returncode": result.get("returncode", -1)
            }
    
    except Exception as e:
        logger.error(f"Error in ffmpeg_mux: {e}")
        return {
            "status": "error",
            "error": str(e)
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
    timeout: int = 300
) -> Dict[str, Any]:
    """
    Demux (separate) streams from a media container into separate files.
    
    This tool extracts:
    - Video streams to separate video files
    - Audio streams to separate audio files (multiple languages/tracks)
    - Subtitle streams to separate subtitle files
    
    Args:
        input_file: Input media file path or dataset
        output_dir: Output directory for extracted streams
        extract_video: Whether to extract video streams
        extract_audio: Whether to extract audio streams
        extract_subtitles: Whether to extract subtitle streams
        video_format: Output format for video streams
        audio_format: Output format for audio streams
        subtitle_format: Output format for subtitle streams
        stream_selection: Specific streams to extract (e.g., {'video': [0], 'audio': [0, 1]})
        timeout: Processing timeout in seconds
        
    Returns:
        Dict containing demuxing results
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
        
        # Create output directory
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Get input media info
        input_info = await ffmpeg_utils.probe_media_info(input_path)
        if input_info["status"] != "success":
            return {
                "status": "error",
                "error": f"Could not probe input file: {input_info.get('error')}"
            }
        
        # Extract streams
        extracted_files = []
        base_name = Path(input_path).stem
        
        # Extract video streams
        if extract_video and input_info["video_streams"]:
            video_streams = stream_selection.get('video', list(range(len(input_info["video_streams"])))) if stream_selection else list(range(len(input_info["video_streams"])))
            
            for i, stream_idx in enumerate(video_streams):
                if stream_idx < len(input_info["video_streams"]):
                    output_file = output_path / f"{base_name}_video_{stream_idx}.{video_format}"
                    
                    args = [
                        "-i", input_path,
                        "-map", f"0:v:{stream_idx}",
                        "-c:v", "copy" if video_format == Path(input_path).suffix[1:] else "libx264",
                        "-an",  # No audio
                        "-y",
                        str(output_file)
                    ]
                    
                    result = await ffmpeg_utils.run_ffmpeg_command(args, timeout=timeout)
                    if result["status"] == "success":
                        extracted_files.append({
                            "type": "video",
                            "stream_index": stream_idx,
                            "file_path": str(output_file),
                            "info": input_info["video_streams"][stream_idx]
                        })
        
        # Extract audio streams
        if extract_audio and input_info["audio_streams"]:
            audio_streams = stream_selection.get('audio', list(range(len(input_info["audio_streams"])))) if stream_selection else list(range(len(input_info["audio_streams"])))
            
            for i, stream_idx in enumerate(audio_streams):
                if stream_idx < len(input_info["audio_streams"]):
                    output_file = output_path / f"{base_name}_audio_{stream_idx}.{audio_format}"
                    
                    args = [
                        "-i", input_path,
                        "-map", f"0:a:{stream_idx}",
                        "-c:a", "copy" if audio_format in ["mp3", "aac"] else "libmp3lame",
                        "-vn",  # No video
                        "-y",
                        str(output_file)
                    ]
                    
                    result = await ffmpeg_utils.run_ffmpeg_command(args, timeout=timeout)
                    if result["status"] == "success":
                        extracted_files.append({
                            "type": "audio",
                            "stream_index": stream_idx,
                            "file_path": str(output_file),
                            "info": input_info["audio_streams"][stream_idx]
                        })
        
        # Extract subtitle streams
        if extract_subtitles and input_info["subtitle_streams"]:
            subtitle_streams = stream_selection.get('subtitle', list(range(len(input_info["subtitle_streams"])))) if stream_selection else list(range(len(input_info["subtitle_streams"])))
            
            for i, stream_idx in enumerate(subtitle_streams):
                if stream_idx < len(input_info["subtitle_streams"]):
                    output_file = output_path / f"{base_name}_subtitle_{stream_idx}.{subtitle_format}"
                    
                    args = [
                        "-i", input_path,
                        "-map", f"0:s:{stream_idx}",
                        "-c:s", "copy" if subtitle_format == "srt" else "srt",
                        "-y",
                        str(output_file)
                    ]
                    
                    result = await ffmpeg_utils.run_ffmpeg_command(args, timeout=timeout)
                    if result["status"] == "success":
                        extracted_files.append({
                            "type": "subtitle",
                            "stream_index": stream_idx,
                            "file_path": str(output_file),
                            "info": input_info["subtitle_streams"][stream_idx]
                        })
        
        return {
            "status": "success",
            "message": "Media demuxing completed successfully",
            "input_file": input_path,
            "output_directory": output_dir,
            "extracted_files": extracted_files,
            "input_info": input_info,
            "extracted_count": {
                "video": len([f for f in extracted_files if f["type"] == "video"]),
                "audio": len([f for f in extracted_files if f["type"] == "audio"]),
                "subtitle": len([f for f in extracted_files if f["type"] == "subtitle"])
            }
        }
    
    except Exception as e:
        logger.error(f"Error in ffmpeg_demux: {e}")
        return {
            "status": "error",
            "error": str(e),
            "input_file": input_file
        }

# Async main functions for MCP registration
async def main() -> Dict[str, Any]:
    """Main function for MCP tool registration."""
    return {
        "status": "success",
        "message": "FFmpeg mux/demux tools initialized",
        "tools": ["ffmpeg_mux", "ffmpeg_demux"],
        "description": "Mux and demux media streams using FFmpeg"
    }

if __name__ == "__main__":
    # Example usage
    test_mux = anyio.run(ffmpeg_mux(
        video_input="video.mp4",
        audio_inputs=["audio1.mp3", "audio2.mp3"],
        output_file="output.mkv"
    ))
    print(f"Mux test result: {test_mux}")
    
    test_demux = anyio.run(ffmpeg_demux(
        input_file="input.mkv",
        output_dir="extracted/",
        extract_video=True,
        extract_audio=True
    ))
    print(f"Demux test result: {test_demux}")
