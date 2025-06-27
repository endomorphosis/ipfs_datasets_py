"""
Media processor that coordinates between different multimedia libraries.

This module provides a unified interface for processing multimedia content
using various backends like FFmpeg and yt-dlp.
"""

import asyncio
import logging
from typing import Dict, List, Any, Optional, Union
from pathlib import Path

from .ytdlp_wrapper import YtDlpWrapper, YTDLP_AVAILABLE
from .ffmpeg_wrapper import FFmpegWrapper, FFMPEG_AVAILABLE

logger = logging.getLogger(__name__)


class MediaProcessor:
    """
    Unified media processor that coordinates different multimedia operations.
    """
    
    def __init__(self, 
                 default_output_dir: Optional[str] = None,
                 enable_logging: bool = True):
        """
        Initialize media processor.
        
        Args:
            default_output_dir: Default directory for output files
            enable_logging: Enable detailed logging
        """
        self.default_output_dir = Path(default_output_dir) if default_output_dir else Path.cwd()
        self.enable_logging = enable_logging
        
        # Initialize component wrappers
        self.ytdlp = YtDlpWrapper(default_output_dir, enable_logging) if YTDLP_AVAILABLE else None
        self.ffmpeg = FFmpegWrapper(default_output_dir, enable_logging) if FFMPEG_AVAILABLE else None
        
        logger.info(f"MediaProcessor initialized - YT-DLP: {YTDLP_AVAILABLE}, FFmpeg: {FFMPEG_AVAILABLE}")
    
    async def download_and_convert(self,
                                 url: str,
                                 output_format: str = "mp4",
                                 quality: str = "best") -> Dict[str, Any]:
        """
        Download video and optionally convert to different format.
        
        Args:
            url: Video URL to download
            output_format: Desired output format
            quality: Quality preference
            
        Returns:
            Dict containing processing results
        """
        try:
            if not self.ytdlp:
                return {
                    "status": "error",
                    "error": "YT-DLP not available for download"
                }
            
            # Download video
            download_result = await self.ytdlp.download_video(
                url=url,
                quality=quality,
                output_dir=str(self.default_output_dir)
            )
            
            if download_result.get("status") != "success":
                return download_result
            
            # If format conversion is needed and FFmpeg is available
            downloaded_file = download_result.get("output_path")
            if downloaded_file and self.ffmpeg and not downloaded_file.endswith(f".{output_format}"):
                convert_path = str(Path(downloaded_file).with_suffix(f".{output_format}"))
                convert_result = await self.ffmpeg.convert_video(downloaded_file, convert_path)
                
                if convert_result.get("status") == "success":
                    download_result["converted_path"] = convert_path
                    download_result["conversion_result"] = convert_result
            
            return download_result
            
        except Exception as e:
            logger.error(f"Error in download_and_convert: {e}")
            return {
                "status": "error",
                "error": str(e)
            }
    
    def get_capabilities(self) -> Dict[str, Any]:
        """
        Get available capabilities and supported operations.
        
        Returns:
            Dict containing capability information
        """
        return {
            "ytdlp_available": YTDLP_AVAILABLE,
            "ffmpeg_available": FFMPEG_AVAILABLE,
            "supported_operations": {
                "download": YTDLP_AVAILABLE,
                "convert": FFMPEG_AVAILABLE,
                "download_and_convert": YTDLP_AVAILABLE and FFMPEG_AVAILABLE
            }
        }
