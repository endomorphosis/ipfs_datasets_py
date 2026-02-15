"""
OpenCV (cv2) processor module for the Omni-Converter.

This module isolates the OpenCV (cv2) dependency and provides functions for
extracting frames and thumbnails from video files in a memory-efficient manner.
"""

import os
import gc
from typing import Any, Optional, Union, BinaryIO
import io

from logger import logger

# TODO Refactor this so that it follows the model of the other processors. Dependency injection, IoC, etc.
# Import optional dependencies # TODO This check should be moved to a constants.py file.
try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    logger.warning("OpenCV (cv2) not available, frame extraction will be limited")
    CV2_AVAILABLE = False


def is_available() -> bool:
    """
    Check if OpenCV (cv2) is available.
    
    Returns:
        True if OpenCV is available, False otherwise.
    """
    return CV2_AVAILABLE


def get_video_properties(file_path: str) -> dict[str, Any]:
    """
    Get video properties using OpenCV.
    
    Args:
        file_path: Path to the video file.
        
    Returns:
        Dictionary with video properties (fps, frame_count, width, height, duration).
        
    Raises:
        ValueError: If OpenCV is not available.
        Exception: If an error occurs during processing.
    """
    if not CV2_AVAILABLE:
        raise ValueError("OpenCV (cv2) is not available. Install it to use this function.")
    
    properties = {
        'fps': 0,
        'frame_count': 0,
        'width': 0,
        'height': 0,
        'duration': 0
    }
    
    try:
        # Open video file with OpenCV
        video = cv2.VideoCapture(file_path)
        
        # Check if video opened successfully
        if not video.isOpened():
            logger.warning(f"Could not open video file: {file_path}")
            video.release()
            return properties
        
        # Get video properties
        properties['fps'] = video.get(cv2.CAP_PROP_FPS)
        properties['frame_count'] = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
        properties['width'] = int(video.get(cv2.CAP_PROP_FRAME_WIDTH))
        properties['height'] = int(video.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        # Calculate duration (in seconds)
        if properties['fps'] > 0 and properties['frame_count'] > 0:
            properties['duration'] = properties['frame_count'] / properties['fps']
        
        # Close video to free resources
        video.release()
        
        return properties
        
    except Exception as e:
        logger.error(f"Error getting video properties with OpenCV: {e}")
        return properties


def extract_frame(file_path: str, time_offset: float = 5.0, max_size: int = 320) -> Optional[bytes]:
    """
    Extract a frame from a video file at a specific time offset.
    
    Args:
        file_path: Path to the video file.
        time_offset: Time in seconds to extract the frame from (default: 5.0).
        max_size: Maximum dimension of the output frame (default: 320).
        
    Returns:
        Frame as bytes in PNG format, or None if extraction failed.
        
    Raises:
        ValueError: If OpenCV is not available.
        Exception: If an error occurs during processing.
    """
    if not CV2_AVAILABLE:
        raise ValueError("OpenCV (cv2) is not available. Install it to use this function.")
    
    try:
        # Open video file with OpenCV
        video = cv2.VideoCapture(file_path)
        
        # Check if video opened successfully
        if not video.isOpened():
            logger.warning(f"Could not open video file: {file_path}")
            video.release()
            return None
        
        # Get video properties
        fps = video.get(cv2.CAP_PROP_FPS)
        frame_count = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
        
        # Calculate frame number to extract
        frame_number = min(int(time_offset * fps), frame_count - 1)
        if frame_number < 0:
            frame_number = 0
        
        # Seek to desired frame
        video.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        
        # Read frame
        success, frame = video.read()
        
        # Close video to free resources immediately
        video.release()
        
        if not success:
            logger.warning(f"Failed to read frame from video: {file_path}")
            return None
        
        # Resize frame while maintaining aspect ratio
        height, width = frame.shape[:2]
        if width > height:
            new_width = max_size
            new_height = int(height * (max_size / width))
        else:
            new_height = max_size
            new_width = int(width * (max_size / height))
            
        resized_frame = cv2.resize(frame, (new_width, new_height))
        
        # Convert frame to PNG
        _, buffer = cv2.imencode('.png', resized_frame)
        
        # Force garbage collection to free OpenCV resources
        del frame, resized_frame
        gc.collect()
        
        return buffer.tobytes()
        
    except Exception as e:
        logger.error(f"Error extracting frame with OpenCV: {e}")
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
        ValueError: If OpenCV is not available.
        Exception: If an error occurs during processing.
    """
    if not CV2_AVAILABLE:
        raise ValueError("OpenCV (cv2) is not available. Install it to use this function.")
    
    frames = []
    
    try:
        # Get video properties
        properties = get_video_properties(file_path)
        duration = properties['duration']
        
        if duration <= 0:
            logger.warning(f"Could not determine video duration: {file_path}")
            return frames
        
        # Calculate time positions for frames (evenly distributed)
        interval = duration / (frame_count + 1)
        time_positions = [interval * (i + 1) for i in range(frame_count)]
        
        # Extract frames at each position
        for i, time_pos in enumerate(time_positions):
            frame_data = extract_frame(file_path, time_pos, max_size)
            
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
        logger.error(f"Error extracting multiple frames with OpenCV: {e}")
        return frames


def process_video_frames(file_path: str, options: dict[str, Any]) -> Optional[dict[str, Any]]:
    """
    Process a video file and extract frames based on options.
    
    Args:
        file_path: Path to the video file.
        options: Processing options:
            - extract_thumbnail: Whether to extract a thumbnail (bool)
            - thumbnail_time: Time offset for thumbnail extraction (float)
            - extract_frames: Whether to extract multiple frames (bool)
            - frame_count: Number of frames to extract (int)
            - max_size: Maximum dimension of output frames (int)
        
    Returns:
        Dictionary with extracted frames and thumbnails, or None if extraction failed.
    """
    if not CV2_AVAILABLE:
        logger.warning("OpenCV (cv2) is not available. Cannot process video frames.")
        return None
    
    result = {
        'thumbnail': None,
        'frames': []
    }
    
    try:
        # Extract thumbnail if requested
        extract_thumbnail = options.get('extract_thumbnail', True)
        if extract_thumbnail:
            time_offset = options.get('thumbnail_time', 5.0)
            max_size = options.get('max_size', 320)
            
            thumbnail = extract_frame(file_path, time_offset, max_size)
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
            
            frames = extract_multiple_frames(file_path, frame_count, max_size)
            if frames:
                result['frames'] = frames
        
        return result
        
    except Exception as e:
        logger.error(f"Error processing video frames: {e}")
        return None