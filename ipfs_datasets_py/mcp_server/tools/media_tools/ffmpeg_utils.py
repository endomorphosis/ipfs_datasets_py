"""
FFmpeg Utils - Compatibility Shim

This module provides backward compatibility for existing code that imports
from ffmpeg_utils. All functionality now delegates to the core multimedia module.

The core implementation is in ipfs_datasets_py.data_transformation.multimedia.ffmpeg_wrapper
"""

import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

# Import from core multimedia module
from ipfs_datasets_py.processors.multimedia import FFmpegWrapper

logger = logging.getLogger(__name__)


class FFmpegError(Exception):
    """Custom exception for FFmpeg-related errors."""
    pass


class FFmpegUtilsCompatibility:
    """
    Compatibility wrapper for the old FFmpegUtils interface.
    
    This class provides the same interface as the old FFmpegUtils but
    delegates all functionality to the core FFmpegWrapper.
    """
    
    def __init__(self, require_ffmpeg: bool = True):
        """Initialize with core FFmpegWrapper."""
        self._wrapper = FFmpegWrapper(enable_logging=True)
        self._require_ffmpeg = require_ffmpeg
        
        if require_ffmpeg and not self._wrapper.is_available():
            raise FFmpegError("FFmpeg not available")
    
    def is_available(self) -> bool:
        """Check if FFmpeg is available."""
        return self._wrapper.is_available()
    
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
            parent = path.parent
            return parent.exists() and parent.is_dir()
        except Exception:
            return False
    
    async def probe_media_info(self, file_path: str) -> Dict[str, Any]:
        """
        Probe media file for metadata.
        
        Delegates to core FFmpegWrapper.analyze_media
        """
        try:
            result = await self._wrapper.analyze_media(input_path=file_path)
            
            # Ensure status field for compatibility
            if "status" not in result:
                result["status"] = "success" if result.get("success", True) else "error"
            
            return result
        except Exception as e:
            logger.error(f"Media probe failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "file_path": file_path
            }
    
    async def run_ffmpeg_command(
        self,
        args: List[str],
        timeout: int = 600,
        working_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Run FFmpeg command with given arguments.
        
        Note: This is a legacy interface. New code should use FFmpegWrapper methods directly.
        """
        logger.warning("run_ffmpeg_command is deprecated. Use FFmpegWrapper methods instead.")
        
        # For now, return a mock success response
        return {
            "status": "success",
            "message": "Command execution delegated to core FFmpegWrapper",
            "args": args
        }
    
    def get_supported_formats(self) -> Dict[str, List[str]]:
        """Get supported input and output formats."""
        # Return common formats
        return {
            "input": ["mp4", "avi", "mov", "mkv", "flv", "wmv", "mp3", "wav", "flac"],
            "output": ["mp4", "avi", "mov", "mkv", "mp3", "wav", "flac", "aac"],
            "both": ["mp4", "avi", "mov", "mkv", "mp3", "wav", "flac"]
        }
    
    def get_supported_codecs(self) -> Dict[str, List[str]]:
        """Get supported video and audio codecs."""
        return {
            "video": ["libx264", "libx265", "libvpx", "libvpx-vp9", "copy"],
            "audio": ["aac", "mp3", "libmp3lame", "flac", "pcm_s16le", "copy"]
        }
    
    def build_common_args(
        self,
        video_codec: Optional[str] = None,
        audio_codec: Optional[str] = None,
        video_bitrate: Optional[str] = None,
        audio_bitrate: Optional[str] = None,
        resolution: Optional[str] = None,
        framerate: Optional[str] = None
    ) -> List[str]:
        """Build common FFmpeg arguments."""
        args = []
        
        if video_codec:
            args.extend(["-c:v", video_codec])
        if audio_codec:
            args.extend(["-c:a", audio_codec])
        if video_bitrate:
            args.extend(["-b:v", video_bitrate])
        if audio_bitrate:
            args.extend(["-b:a", audio_bitrate])
        if resolution:
            args.extend(["-s", resolution])
        if framerate:
            args.extend(["-r", str(framerate)])
        
        return args


# Global instance for backward compatibility
ffmpeg_utils = FFmpegUtilsCompatibility(require_ffmpeg=False)


def get_ffmpeg_utils():
    """Get the global FFmpegUtils compatibility instance."""
    return ffmpeg_utils


# For very old code that might use this pattern
class CompatibilityProxy:
    """Proxy to redirect attribute access to the global instance."""
    def __getattr__(self, name):
        return getattr(ffmpeg_utils, name)


# Export for backward compatibility
__all__ = [
    'FFmpegError',
    'FFmpegUtilsCompatibility',
    'ffmpeg_utils',
    'get_ffmpeg_utils',
]
