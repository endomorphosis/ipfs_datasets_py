"""
Video processor module for the Omni-Converter.

This module provides a processor for extracting information from video files,
including thumbnails and frames, using a memory-efficient approach.
"""

import os
import tempfile
import subprocess
from typing import Any, Optional, Union, BinaryIO
from datetime import timedelta
import io
import gc

from logger import logger

# Import optional dependencies
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    logger.warning("PIL not available, thumbnail generation will be limited")
    HAS_PIL = False

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    logger.warning("OpenCV not available, using fallback for video frame extraction")
    HAS_CV2 = False


class VideoProcessor:
    """
    Processor for video files.
    
    Extracts thumbnails, frames, and information from video files using
    memory-efficient approaches.
    """
    
    def __init__(self):
        """Initialize the video processor."""
        self._supported_formats = {'mp4', 'webm', 'avi', 'mkv', 'mov'}
    
    def can_process(self, format_name: str) -> bool:
        """
        Check if the processor can handle the given format.
        
        Args:
            format_name: The format to check.
            
        Returns:
            True if the format is supported, False otherwise.
        """
        return format_name in self.supported_formats and (HAS_PIL or HAS_CV2)

    @property
    def supported_formats(self) -> list[str]:
        """
        Get the list of formats supported by this processor.
        # TODO Add in support to check if ffmpeg is installed.
        
        Returns:
            A list of format names supported by this processor.
        """
        return self._supported_formats

    def extract_thumbnail(self, file_path: str, options: Optional[dict[str, Any]] = None) -> Optional[bytes]:
        """
        Extract a thumbnail from a video file using memory-efficient methods.
        
        Args:
            file_path: Path to the video file.
            options: Extraction options including:
                - time_offset: Time in seconds to extract thumbnail from (default: 5).
                - max_size: Maximum thumbnail dimension (default: 320).
                
        Returns:
            Thumbnail as bytes in PNG format, or None if extraction failed.
        """
        options = options or {}
        time_offset = options.get('time_offset', 5)  # Default to 5 seconds in
        max_size = options.get('max_size', 320)      # Default max dimension 320px
        
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
                
                # Try OpenCV as a fallback if available
                if HAS_CV2:
                    return self._extract_thumbnail_cv2(file_path, time_offset, max_size)
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
            logger.error(f"Error extracting thumbnail: {e}")
            
            # Try OpenCV as a fallback if available
            if HAS_CV2:
                return self._extract_thumbnail_cv2(file_path, time_offset, max_size)
            return None
            
        except Exception as e:
            logger.error(f"Unexpected error extracting thumbnail: {e}")
            return None
    
    def _extract_thumbnail_cv2(self, file_path: str, time_offset: float, max_size: int) -> Optional[bytes]:
        """
        Extract thumbnail using OpenCV (fallback method).
        
        Args:
            file_path: Path to the video file.
            time_offset: Time in seconds to extract thumbnail from.
            max_size: Maximum thumbnail dimension.
            
        Returns:
            Thumbnail as bytes in PNG format, or None if extraction failed.
        """
        if not HAS_CV2:
            return None
            
        try:
            # Open video file with OpenCV
            video = cv2.VideoCapture(file_path)
            
            # Check if video opened successfully
            if not video.isOpened():
                logger.warning(f"Could not open video file: {file_path}")
                return None
            
            # Get video properties
            fps = video.get(cv2.CAP_PROP_FPS)
            frame_count = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
            
            # Calculate frame number to extract
            frame_number = min(int(time_offset * fps), frame_count - 1)
            
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
            logger.error(f"Error extracting thumbnail with OpenCV: {e}")
            return None
    
    def extract_frame_at_time(self, file_path: str, time_position: float, 
                             options: Optional[dict[str, Any]] = None) -> Optional[bytes]:
        """
        Extract a specific frame at a given time position.
        
        Args:
            file_path: Path to the video file.
            time_position: Time in seconds to extract frame from.
            options: Extraction options.
            
        Returns:
            Frame as bytes in PNG format, or None if extraction failed.
        """
        options = options or {}
        options['time_offset'] = time_position
        return self.extract_thumbnail(file_path, options)
    
    def extract_key_frames(self, file_path: str, 
                          options: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
        """
        Extract multiple key frames from a video at regular intervals.
        Uses memory-efficient streaming approach to avoid loading entire video.
        
        Args:
            file_path: Path to the video file.
            options: Extraction options including:
                - frame_count: Number of frames to extract (default: 5).
                - max_size: Maximum frame dimension (default: 320).
                
        Returns:
            List of dictionaries containing frame data and timestamps.
        """
        options = options or {}
        frame_count = options.get('frame_count', 5)  # Default to 5 frames
        max_size = options.get('max_size', 320)      # Default max dimension 320px
        
        try:
            # Get video duration using ffprobe
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
            except (ValueError, UnicodeDecodeError):
                # Fallback to estimating duration
                duration = 60.0  # Default assumption of 1 minute
            
            # Calculate time positions for frames
            interval = duration / (frame_count + 1)
            time_positions = [interval * (i + 1) for i in range(frame_count)]
            
            # Extract frames
            frames = []
            for i, time_pos in enumerate(time_positions):
                # Extract thumbnail at this position
                frame_data = self.extract_thumbnail(
                    file_path, 
                    {'time_offset': time_pos, 'max_size': max_size}
                )
                
                if frame_data:
                    # Format timestamp as HH:MM:SS
                    timestamp_str = str(timedelta(seconds=int(time_pos)))
                    
                    frames.append({
                        'index': i,
                        'time_position': time_pos,
                        'timestamp': timestamp_str,
                        'data': frame_data,
                        'format': 'png'
                    })
            
            return frames
            
        except (subprocess.SubprocessError, OSError) as e:
            logger.error(f"{type(e).__name__} extracting key frames: {e}")
            return []
            
        except Exception as e:
            logger.error(f"Unexpected error extracting key frames: {e}")
            return []
    
    def extract_video_info(self, file_path: str) -> dict[str, Any]:
        """
        Extract video information using ffprobe.
        Uses a memory-efficient approach to avoid loading the entire file.
        
        Args:
            file_path: Path to the video file.
            
        Returns:
            Dictionary with video information including:
                - duration: Video duration in seconds.
                - width: Video width in pixels.
                - height: Video height in pixels.
                - codec: Video codec name.
                - fps: Frames per second.
                - bitrate: Video bitrate.
        """
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
                import json
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
            
        except (subprocess.SubprocessError, OSError) as e:
            logger.error(f"Error extracting video info: {e}")
            return info
            
        except Exception as e:
            logger.error(f"Unexpected error extracting video info: {e}")
            return info


# Global video processor instance
video_processor = VideoProcessor()
