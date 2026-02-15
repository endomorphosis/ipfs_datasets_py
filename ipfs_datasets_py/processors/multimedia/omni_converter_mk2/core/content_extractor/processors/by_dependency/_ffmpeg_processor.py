"""
FFmpeg processor module for the Omni-Converter.

This module isolates the FFmpeg CLI dependency and provides functions for
video processing, thumbnail extraction, and metadata retrieval in a memory-efficient manner.
"""

import os
import tempfile
import subprocess
import json
from typing import Any, Optional, Union, BinaryIO
from datetime import timedelta
from core.content_extractor._content_extractor_constants import Constants

from logger import logger

# TODO Refactor this so that it follows the model of the other processors. Dependency injection, IoC, etc.
# Check if ffmpeg and ffprobe are available by running a simple command # TODO This check should be moved to a constants.py file.
try:
    subprocess.run(['ffmpeg', '-version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
    subprocess.run(['ffprobe', '-version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
    FFMPEG_AVAILABLE = True
except (subprocess.SubprocessError, OSError, FileNotFoundError):
    logger.warning("FFmpeg not found or not working, video processing will be limited")
    FFMPEG_AVAILABLE = False


def is_available() -> bool:
    """
    Check if FFmpeg is available.
    
    Returns:
        True if FFmpeg is available, False otherwise.
    """
    return FFMPEG_AVAILABLE


def extract_thumbnail(file_path: str, time_offset: float = 5.0, max_size: int = 320) -> Optional[bytes]:
    """
    Extract a thumbnail from a video file using FFmpeg.
    
    Args:
        file_path: Path to the video file.
        time_offset: Time in seconds to extract the thumbnail from (default: 5.0).
        max_size: Maximum dimension of the output thumbnail (default: 320).
        
    Returns:
        Thumbnail as bytes in PNG format, or None if extraction failed.
        
    Raises:
        ValueError: If FFmpeg is not available.
        Exception: If an error occurs during processing.
    """
    if not FFMPEG_AVAILABLE:
        raise ValueError("FFmpeg is not available. Install it to use this function.")
    
    try:
        # Create a temporary file for the thumbnail
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
            temp_thumbnail_path = tmp_file.name
        
        # Use ffmpeg to extract a frame (much more memory efficient than loading the video)
        command = [
            'ffmpeg', 
            '-i', file_path,                   # Input file
            '-ss', str(time_offset),           # Seek to time position
            '-frames:v', '1',                  # Extract one frame
            '-vf', f'scale={max_size}:-1',     # Scale preserving aspect ratio
            '-y',                              # Overwrite output file
            temp_thumbnail_path                # Output file
        ]
        
        # Run ffmpeg process
        ffmpeg_process = subprocess.run(
            command, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            timeout=30  # Timeout after 30 seconds
        )
        
        # Check if thumbnail was successfully created
        if ffmpeg_process.returncode != 0:
            logger.warning(f"FFmpeg extraction failed: {ffmpeg_process.stderr.decode()}")
            try:
                os.unlink(temp_thumbnail_path)
            except OSError:
                pass
            return None
        
        # Read the thumbnail file
        with open(temp_thumbnail_path, 'rb') as f:
            thumbnail_data = f.read()
        
        # Clean up temporary file
        try:
            os.unlink(temp_thumbnail_path)
        except OSError:
            pass
        
        return thumbnail_data
        
    except (subprocess.SubprocessError, OSError) as e:
        logger.error(f"Error extracting thumbnail with FFmpeg: {e}")
        return None
    
    except Exception as e:
        logger.error(f"Unexpected error extracting thumbnail with FFmpeg: {e}")
        return None


def extract_multiple_frames(file_path: str, frame_count: int = 5, max_size: int = 320) -> list[dict[str, Any]]:
    """
    Extract multiple frames at regular intervals throughout the video.
    
    Args:
        file_path: Path to the video file.
        frame_count: Number of frames to extract (default: 5).
        max_size: Maximum dimension of the output frames (default: 320).
        
    Returns:
        List of dictionaries, each containing frame data and metadata.
        
    Raises:
        ValueError: If FFmpeg is not available.
        Exception: If an error occurs during processing.
    """
    if not FFMPEG_AVAILABLE:
        raise ValueError("FFmpeg is not available. Install it to use this function.")
    
    frames = []
    
    try:
        # Get video duration using ffprobe
        duration = get_video_duration(file_path)
        
        if duration <= 0:
            logger.warning(f"Could not determine video duration: {file_path}")
            return frames
        
        # Calculate time positions for frames (evenly distributed)
        interval = duration / (frame_count + 1)
        time_positions = [interval * (i + 1) for i in range(frame_count)]
        
        # Extract frames at each position
        for i, time_pos in enumerate(time_positions):
            frame_data = extract_thumbnail(file_path, time_pos, max_size)
            
            if frame_data:
                # Convert time to HH:MM:SS format
                hours = int(time_pos / 3600)
                minutes = int((time_pos % 3600) / 60)
                seconds = int(time_pos % 60)
                timestamp_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                
                frames.append({
                    'index': i,
                    'time_position': time_pos,
                    'timestamp': timestamp_str,
                    'data': frame_data,
                    'format': 'png'
                })
        
        return frames
        
    except Exception as e:
        logger.error(f"Error extracting multiple frames with FFmpeg: {e}")
        return frames


def get_video_duration(file_path: str) -> float:
    """
    Get video duration in seconds using ffprobe.
    
    Args:
        file_path: Path to the video file.
        
    Returns:
        Duration in seconds, or 0 if retrieval failed.
        
    Raises:
        ValueError: If FFmpeg is not available.
        Exception: If an error occurs during processing.
    """
    if not FFMPEG_AVAILABLE:
        raise ValueError("FFmpeg is not available. Install it to use this function.")
    
    try:
        # Use ffprobe to get video duration
        duration_cmd = [
            'ffprobe', 
            '-v', 'error', 
            '-show_entries', 'format=duration', 
            '-of', 'default=noprint_wrappers=1:nokey=1', 
            file_path
        ]
        
        duration_result = subprocess.run(
            duration_cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            timeout=10
        )
        
        # Parse duration
        try:
            duration = float(duration_result.stdout.decode().strip())
            return duration
        except (ValueError, UnicodeDecodeError):
            # Fallback to estimating duration
            logger.warning(f"Could not parse video duration for {file_path}")
            return 0.0
        
    except Exception as e:
        logger.error(f"Error getting video duration with FFmpeg: {e}")
        return 0.0


def get_video_info(file_path: str) -> dict[str, Any]:
    """
    Get comprehensive video information using ffprobe.
    
    Args:
        file_path: Path to the video file.
        
    Returns:
        Dictionary with video information including duration, resolution, codecs, etc.
        
    Raises:
        ValueError: If FFmpeg is not available.
        Exception: If an error occurs during processing.
    """
    if not FFMPEG_AVAILABLE:
        raise ValueError("FFmpeg is not available. Install it to use this function.")
    
    # Initialize info dictionary with default values
    info = {
        'duration': 0,
        'width': 0,
        'height': 0,
        'codec': 'unknown',
        'fps': 0,
        'bitrate': 0
    }
    
    try:
        # Use ffprobe to get video information
        cmd = [
            'ffprobe', 
            '-v', 'error', 
            '-select_streams', 'v:0',  # First video stream
            '-show_entries', 'stream=width,height,codec_name,r_frame_rate,bit_rate',
            '-show_entries', 'format=duration',
            '-of', 'json', 
            file_path
        ]
        
        ffprobe_result = subprocess.run(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            timeout=10
        )
        
        # Parse JSON output
        if ffprobe_result.returncode == 0:
            probe_data = json.loads(ffprobe_result.stdout.decode())
            
            # Extract format information
            if 'format' in probe_data:
                fmt = probe_data['format']
                if 'duration' in fmt:
                    try:
                        info['duration'] = float(fmt['duration'])
                    except (ValueError, TypeError):
                        pass
            
            # Extract stream information
            if 'streams' in probe_data and probe_data['streams']:
                stream = probe_data['streams'][0]  # First video stream
                
                # Extract dimensions
                if 'width' in stream:
                    info['width'] = stream['width']
                if 'height' in stream:
                    info['height'] = stream['height']
                
                # Extract codec
                if 'codec_name' in stream:
                    info['codec'] = stream['codec_name']
                
                # Extract framerate
                if 'r_frame_rate' in stream:
                    # Frame rate is often in format "num/den"
                    try:
                        num, den = stream['r_frame_rate'].split('/')
                        info['fps'] = float(num) / float(den)
                    except (ValueError, ZeroDivisionError):
                        pass
                
                # Extract bitrate
                if 'bit_rate' in stream:
                    try:
                        info['bitrate'] = int(stream['bit_rate'])
                    except (ValueError, TypeError):
                        pass
                elif 'bit_rate' in fmt:
                    try:
                        info['bitrate'] = int(fmt['bit_rate'])
                    except (ValueError, TypeError):
                        pass
        
        return info
        
    except Exception as e:
        logger.error(f"Error getting video info with FFmpeg: {e}")
        return info


def process_video_file(file_path: str, options: dict[str, Any]) -> dict[str, Any]:
    """
    Process a video file and extract information, thumbnails, and frames based on options.
    
    Args:
        file_path: Path to the video file.
        options: Processing options:
            - extract_info: Whether to extract video information (bool)
            - extract_thumbnail: Whether to extract a thumbnail (bool)
            - thumbnail_time: Time offset for thumbnail extraction (float)
            - extract_frames: Whether to extract multiple frames (bool)
            - frame_count: Number of frames to extract (int)
            - max_size: Maximum dimension of output frames (int)
        
    Returns:
        Dictionary with extracted information, thumbnails, and frames.
    """
    if not FFMPEG_AVAILABLE:
        logger.warning("FFmpeg is not available. Cannot process video file.")
        return {
            'success': False,
            'error': 'FFmpeg not available'
        }
    
    result = {
        'success': True,
        'info': None,
        'thumbnail': None,
        'frames': []
    }
    
    try:
        # Extract video information if requested
        extract_info = options.get('extract_info', True)
        if extract_info:
            result['info'] = get_video_info(file_path)
        
        # Extract thumbnail if requested
        extract_thumbnail = options.get('extract_thumbnail', True)
        if extract_thumbnail:
            # Default to 25% of video duration, with fallback to 5 seconds
            if result['info'] and result['info']['duration'] > 0:
                default_time = result['info']['duration'] * 0.25 # TODO This is a magic number and should be moved to a constants.py file.
            else:
                default_time = 5.0 # TODO This is a magic number and should be moved to a constants.py file.
            
            time_offset = options.get('thumbnail_time', default_time)
            max_size = options.get('max_size', 320)
            
            thumbnail = extract_thumbnail(file_path, time_offset, max_size)
            if thumbnail:
                result['thumbnail'] = {
                    'data': thumbnail,
                    'format': 'png',
                    'time_offset': time_offset
                }
        
        # Extract multiple frames if requested
        extract_frames = options.get('extract_frames', False)
        if extract_frames:
            frame_count = options.get('frame_count', 5)
            max_size = options.get('max_size', 320)
            
            result['frames'] = extract_multiple_frames(file_path, frame_count, max_size)
        
        return result
        
    except Exception as e:
        logger.error(f"Error processing video file: {e}")
        return {
            'success': False,
            'error': str(e)
        }