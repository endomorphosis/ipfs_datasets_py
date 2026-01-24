# ipfs_datasets_py/mcp_server/tools/media_tools/ffmpeg_utils.py
"""
Core FFmpeg utilities and helpers for media processing tools.

This module provides common functionality for FFmpeg operations including
path validation, command construction, process execution, and error handling.
"""
import anyio
import json
import os
import subprocess
import shutil
import tempfile
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Union, Tuple
import logging

from ipfs_datasets_py.mcp_server.logger import logger

class FFmpegError(Exception):
    """Custom exception for FFmpeg-related errors."""
    pass

class FFmpegUtils:
    """Utility class for FFmpeg operations."""
    
    def __init__(self, require_ffmpeg: bool = True):
        """Initialize FFmpeg utilities with optional FFmpeg requirement"""
        if require_ffmpeg:
            self.ffmpeg_path = self._find_ffmpeg()
            self.ffprobe_path = self._find_ffprobe()
        else:
            self.ffmpeg_path = None
            self.ffprobe_path = None
            
    def _find_ffmpeg(self) -> str:
        """Find FFmpeg executable path."""
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            raise FFmpegError("FFmpeg not found. Please install FFmpeg and ensure it's in PATH.")
        return ffmpeg_path
    
    def _find_ffprobe(self) -> str:
        """Find FFprobe executable path."""
        ffprobe_path = shutil.which("ffprobe")
        if not ffprobe_path:
            raise FFmpegError("FFprobe not found. Please install FFmpeg with FFprobe.")
        return ffprobe_path
    
    def is_available(self) -> bool:
        """Check if FFmpeg is available"""
        return self.ffmpeg_path is not None and self.ffprobe_path is not None
    
    def validate_input_file(self, file_path: str) -> bool:
        """Validate input media file exists and is accessible."""
        try:
            path = Path(file_path)
            return path.exists() and path.is_file()
        except Exception:
            return False
    
    def validate_output_path(self, output_path: str) -> bool:
        """Validate output path is writable."""
        try:
            path = Path(output_path)
            # Check if parent directory exists and is writable
            parent = path.parent
            return parent.exists() and os.access(parent, os.W_OK)
        except Exception:
            return False
    
    def get_supported_formats(self) -> Dict[str, List[str]]:
        """Get supported input and output formats."""
        try:
            # Get formats
            result = subprocess.run(
                [self.ffmpeg_path, "-formats"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            formats = {"input": [], "output": [], "both": []}
            lines = result.stdout.split('\n')
            
            for line in lines:
                if line.strip() and not line.startswith('--') and not line.startswith('File formats:'):
                    parts = line.split()
                    if len(parts) >= 3:
                        flags = parts[0]
                        format_name = parts[1]
                        
                        if 'D' in flags:  # Demuxing supported
                            formats["input"].append(format_name)
                        if 'E' in flags:  # Muxing supported
                            formats["output"].append(format_name)
                        if 'D' in flags and 'E' in flags:
                            formats["both"].append(format_name)
            
            return formats
        except Exception as e:
            logger.warning(f"Could not get supported formats: {e}")
            return {"input": [], "output": [], "both": []}
    
    def get_supported_codecs(self) -> Dict[str, List[str]]:
        """Get supported audio and video codecs."""
        try:
            result = subprocess.run(
                [self.ffmpeg_path, "-codecs"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            codecs = {"video": [], "audio": [], "subtitle": []}
            lines = result.stdout.split('\n')
            
            for line in lines:
                if line.strip() and not line.startswith('--') and not line.startswith('Codecs:'):
                    parts = line.split()
                    if len(parts) >= 3:
                        flags = parts[0]
                        codec_name = parts[1]
                        
                        if 'V' in flags:  # Video codec
                            codecs["video"].append(codec_name)
                        elif 'A' in flags:  # Audio codec
                            codecs["audio"].append(codec_name)
                        elif 'S' in flags:  # Subtitle codec
                            codecs["subtitle"].append(codec_name)
            
            return codecs
        except Exception as e:
            logger.warning(f"Could not get supported codecs: {e}")
            return {"video": [], "audio": [], "subtitle": []}
    
    async def run_ffmpeg_command(
        self,
        args: List[str],
        timeout: int = 300,
        capture_output: bool = True
    ) -> Dict[str, Any]:
        """
        Run FFmpeg command asynchronously.
        
        Args:
            args: Full FFmpeg command arguments (including ffmpeg path)
            timeout: Command timeout in seconds
            capture_output: Whether to capture stdout/stderr
            
        Returns:
            Dict with execution results
        """
        # If args already includes ffmpeg path, use as-is, otherwise prepend it
        if args and args[0] != self.ffmpeg_path:
            cmd = args  # Assume full command provided
        else:
            cmd = args
        try:
            logger.info(f"Running FFmpeg command: {' '.join(cmd)}")
            start_time = time.time()
            
            if capture_output:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
                end_time = time.time()
                
                return {
                    "status": "success" if process.returncode == 0 else "error",
                    "returncode": process.returncode,
                    "stdout": stdout.decode('utf-8', errors='replace'),
                    "stderr": stderr.decode('utf-8', errors='replace'),
                    "command": ' '.join(cmd),
                    "duration": end_time - start_time
                }
            else:
                process = await asyncio.create_subprocess_exec(*cmd)
                returncode = await asyncio.wait_for(
                    process.wait(),
                    timeout=timeout
                )
                end_time = time.time()
                
                return {
                    "status": "success" if returncode == 0 else "error",
                    "returncode": returncode,
                    "command": ' '.join(cmd),
                    "duration": end_time - start_time
                }
                
        except TimeoutError:
            return {
                "status": "error",
                "error": "Command timed out",
                "timeout": timeout,
                "command": ' '.join(cmd)
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "command": ' '.join(cmd)
            }
    
    async def probe_media_info(self, file_path: str) -> Dict[str, Any]:
        """
        Probe media file for information using FFprobe.
        
        Args:
            file_path: Path to media file
            
        Returns:
            Dict with media information
        """
        try:
            cmd = [
                self.ffprobe_path,
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                file_path
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                return {
                    "status": "error",
                    "error": stderr.decode('utf-8', errors='replace')
                }
            
            info = json.loads(stdout.decode('utf-8'))
            
            # Parse and structure the information
            result = {
                "status": "success",
                "file_path": file_path,
                "format": info.get("format", {}),
                "streams": info.get("streams", []),
                "video_streams": [],
                "audio_streams": [],
                "subtitle_streams": []
            }
            
            # Categorize streams
            for stream in result["streams"]:
                codec_type = stream.get("codec_type", "").lower()
                if codec_type == "video":
                    result["video_streams"].append(stream)
                elif codec_type == "audio":
                    result["audio_streams"].append(stream)
                elif codec_type == "subtitle":
                    result["subtitle_streams"].append(stream)
            
            return result
            
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "file_path": file_path
            }
    
    def build_common_args(
        self,
        input_file: str,
        output_file: str,
        video_codec: Optional[str] = None,
        audio_codec: Optional[str] = None,
        video_bitrate: Optional[str] = None,
        audio_bitrate: Optional[str] = None,
        resolution: Optional[str] = None,
        framerate: Optional[str] = None,
        overwrite: bool = True
    ) -> List[str]:
        """
        Build common FFmpeg arguments.
        
        Args:
            input_file: Input file path
            output_file: Output file path
            video_codec: Video codec (e.g., 'libx264', 'libx265')
            audio_codec: Audio codec (e.g., 'aac', 'mp3')
            video_bitrate: Video bitrate (e.g., '1000k', '2M')
            audio_bitrate: Audio bitrate (e.g., '128k', '320k')
            resolution: Resolution (e.g., '1920x1080', '1280x720')
            framerate: Frame rate (e.g., '30', '60')
            overwrite: Whether to overwrite output file
            
        Returns:
            List of FFmpeg arguments
        """
        args = []
        
        # Input file
        args.extend(["-i", input_file])
        
        # Video codec
        if video_codec:
            args.extend(["-c:v", video_codec])
        
        # Audio codec
        if audio_codec:
            args.extend(["-c:a", audio_codec])
        
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
        
        # Overwrite output file
        if overwrite:
            args.append("-y")
        
        # Output file
        args.append(output_file)
        
        return args
    
    def parse_time_format(self, time_str: str) -> float:
        """
        Parse time string to seconds.
        
        Args:
            time_str: Time string (e.g., '00:01:30', '90', '1:30')
            
        Returns:
            Time in seconds
        """
        try:
            if ':' in time_str:
                parts = time_str.split(':')
                if len(parts) == 2:  # MM:SS
                    return int(parts[0]) * 60 + float(parts[1])
                elif len(parts) == 3:  # HH:MM:SS
                    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            else:
                return float(time_str)
        except ValueError:
            raise FFmpegError(f"Invalid time format: {time_str}")
        
        # Fallback for unexpected format
        raise FFmpegError(f"Unsupported time format: {time_str}")
    
    def format_time(self, seconds: float) -> str:
        """
        Format seconds to HH:MM:SS.mmm format.
        
        Args:
            seconds: Time in seconds
            
        Returns:
            Formatted time string
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"

# Global instance - lazy loaded to avoid import-time dependency check
_ffmpeg_utils_instance = None

def get_ffmpeg_utils():
    """Get the FFmpeg utils instance, creating it lazily if needed."""
    global _ffmpeg_utils_instance
    if _ffmpeg_utils_instance is None:
        _ffmpeg_utils_instance = FFmpegUtils()
    return _ffmpeg_utils_instance

# Legacy compatibility - will raise error if FFmpeg not available
# This maintains the API but defers the error to actual usage
class _LazyFFmpegUtils:
    def __getattr__(self, name):
        return getattr(get_ffmpeg_utils(), name)
        
ffmpeg_utils = _LazyFFmpegUtils()

# Global instance
# Global instance - lazy initialization to handle missing FFmpeg gracefully
try:
    ffmpeg_utils = FFmpegUtils(require_ffmpeg=True)
except FFmpegError:
    # Create instance without FFmpeg for testing/development
    ffmpeg_utils = FFmpegUtils(require_ffmpeg=False)
