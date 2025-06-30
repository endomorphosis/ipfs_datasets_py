"""
YT-DLP wrapper for downloading videos and audio from various platforms.

This module provides a comprehensive interface to yt-dlp for downloading
content from YouTube, Vimeo, SoundCloud, and many other platforms.
"""

import asyncio
import json
import logging
import tempfile
from pathlib import Path
from typing import Dict, List, Any, Optional, Union, Callable
import uuid
import time
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    import yt_dlp
    YTDLP_AVAILABLE = True
except ImportError:
    YTDLP_AVAILABLE = False
    logger.warning("yt-dlp not available. Install with: pip install yt-dlp")


class YtDlpWrapper:
    """
    Wrapper class for yt-dlp functionality with async support and enhanced features.
    """
    
    def __init__(self, 
                 default_output_dir: Optional[str] = None,
                 enable_logging: bool = True,
                 default_quality: str = "best"):
        """
        Initialize YT-DLP wrapper.
        
        Args:
            default_output_dir: Default directory for downloads
            enable_logging: Enable detailed logging
            default_quality: Default quality setting
        """
        self.default_output_dir = Path(default_output_dir or tempfile.gettempdir())
        self.enable_logging = enable_logging
        self.default_quality = default_quality
        self.downloads = {}  # Track active downloads
        
        if not YTDLP_AVAILABLE:
            raise ImportError("yt-dlp is required but not installed. Install with: pip install yt-dlp")
    
    async def download_video(self, 
                           url: str,
                           output_path: Optional[str] = None,
                           quality: Optional[str] = None,
                           format_selector: Optional[str] = None,
                           audio_only: bool = False,
                           extract_info_only: bool = False,
                           progress_callback: Optional[Callable] = None,
                           **kwargs) -> Dict[str, Any]:
        """
        Download video from URL with comprehensive options.
        
        Args:
            url: Video URL to download
            output_path: Custom output path
            quality: Quality setting (best, worst, specific height like 720p)
            format_selector: Custom format selector
            audio_only: Download audio only
            extract_info_only: Only extract metadata, don't download
            progress_callback: Progress callback function
            **kwargs: Additional yt-dlp options
            
        Returns:
            Dict containing download results and metadata
        """
        try:
            download_id = str(uuid.uuid4())
            
            # Setup output path
            if output_path:
                output_dir = Path(output_path).parent
                filename_template = Path(output_path).name
            else:
                output_dir = self.default_output_dir
                filename_template = "%(title)s.%(ext)s"
            
            # Create output directory
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Build yt-dlp options
            ydl_opts = {
                'outtmpl': str(output_dir / filename_template),
                'writeinfojson': True,
                'writesubtitles': True,
                'writeautomaticsub': True,
                'ignoreerrors': False,
                'no_warnings': not self.enable_logging,
            }
            
            # Format selection
            if audio_only:
                ydl_opts['format'] = 'bestaudio/best'
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': kwargs.get('audio_codec', 'mp3'),
                    'preferredquality': kwargs.get('audio_quality', '192'),
                }]
            elif format_selector:
                ydl_opts['format'] = format_selector
            elif quality:
                if quality == 'best':
                    ydl_opts['format'] = 'best'
                elif quality == 'worst':
                    ydl_opts['format'] = 'worst'
                else:
                    # Handle specific quality like "720p"
                    ydl_opts['format'] = f'best[height<={quality.replace("p", "")}]'
            else:
                ydl_opts['format'] = self.default_quality
            
            # Add custom options
            ydl_opts.update(kwargs)
            
            # Progress hook
            if progress_callback:
                def progress_hook(d):
                    if progress_callback:
                        progress_callback(download_id, d)
                ydl_opts['progress_hooks'] = [progress_hook]
            
            # Track download
            self.downloads[download_id] = {
                'url': url,
                'status': 'starting',
                'start_time': time.time(),
                'output_dir': str(output_dir)
            }
            
            # Execute download in thread pool
            result = await asyncio.get_event_loop().run_in_executor(
                None, self._download_with_ytdlp, url, ydl_opts, extract_info_only
            )
            
            # Update tracking
            self.downloads[download_id].update({
                'status': 'completed' if result['status'] == 'success' else 'failed',
                'end_time': time.time(),
                'result': result
            })
            
            result['download_id'] = download_id
            return result
            
        except Exception as e:
            error_result = {
                'status': 'error',
                'error': str(e),
                'url': url,
                'download_id': download_id if 'download_id' in locals() else None
            }
            
            if 'download_id' in locals():
                self.downloads[download_id].update({
                    'status': 'failed',
                    'end_time': time.time(),
                    'error': str(e)
                })
            
            logger.error(f"Download failed for {url}: {e}")
            return error_result
    
    def _download_with_ytdlp(self, url: str, ydl_opts: Dict, extract_only: bool) -> Dict[str, Any]:
        """
        Execute yt-dlp download in synchronous context.
        """
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if extract_only:
                    info = ydl.extract_info(url, download=False)
                    return {
                        'status': 'success',
                        'action': 'info_extracted',
                        'info': info,
                        'title': info.get('title'),
                        'duration': info.get('duration'),
                        'uploader': info.get('uploader'),
                        'upload_date': info.get('upload_date'),
                        'view_count': info.get('view_count'),
                        'formats': info.get('formats', [])
                    }
                else:
                    info = ydl.download([url])
                    return {
                        'status': 'success',
                        'action': 'downloaded',
                        'url': url,
                        'output_path': ydl_opts['outtmpl'],
                        'info': info
                    }
                    
        except yt_dlp.DownloadError as e:
            return {
                'status': 'error',
                'error': f"Download error: {str(e)}",
                'url': url
            }
        except Exception as e:
            return {
                'status': 'error', 
                'error': f"Unexpected error: {str(e)}",
                'url': url
            }
    
    async def download_playlist(self,
                              playlist_url: str,
                              output_dir: Optional[str] = None,
                              max_downloads: Optional[int] = None,
                              quality: Optional[str] = None,
                              progress_callback: Optional[Callable] = None,
                              **kwargs) -> Dict[str, Any]:
        """
        Download entire playlist from URL.
        
        Args:
            playlist_url: Playlist URL
            output_dir: Output directory for playlist items
            max_downloads: Maximum number of items to download
            quality: Quality setting for all items
            progress_callback: Progress callback function
            **kwargs: Additional yt-dlp options
            
        Returns:
            Dict containing playlist download results
        """
        try:
            download_id = str(uuid.uuid4())
            output_path = Path(output_dir or self.default_output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            
            ydl_opts = {
                'outtmpl': str(output_path / '%(playlist)s/%(title)s.%(ext)s'),
                'writeinfojson': True,
                'ignoreerrors': True,
                'no_warnings': not self.enable_logging,
            }
            
            if max_downloads:
                ydl_opts['playlistend'] = max_downloads
            
            if quality:
                ydl_opts['format'] = quality
            
            ydl_opts.update(kwargs)
            
            # Progress tracking
            downloaded_items = []
            failed_items = []
            
            def playlist_progress_hook(d):
                if d['status'] == 'finished':
                    downloaded_items.append(d['filename'])
                elif d['status'] == 'error':
                    failed_items.append(d.get('filename', 'unknown'))
                
                if progress_callback:
                    progress_callback(download_id, {
                        'downloaded': len(downloaded_items),
                        'failed': len(failed_items),
                        'current': d
                    })
            
            ydl_opts['progress_hooks'] = [playlist_progress_hook]
            
            # Track download
            self.downloads[download_id] = {
                'url': playlist_url,
                'type': 'playlist',
                'status': 'starting',
                'start_time': time.time(),
                'output_dir': str(output_path)
            }
            
            # Execute download
            result = await asyncio.get_event_loop().run_in_executor(
                None, self._download_playlist_with_ytdlp, playlist_url, ydl_opts
            )
            
            result.update({
                'download_id': download_id,
                'downloaded_items': downloaded_items,
                'failed_items': failed_items,
                'total_downloaded': len(downloaded_items),
                'total_failed': len(failed_items)
            })
            
            # Update tracking
            self.downloads[download_id].update({
                'status': 'completed',
                'end_time': time.time(),
                'result': result
            })
            
            return result
            
        except Exception as e:
            error_result = {
                'status': 'error',
                'error': str(e),
                'playlist_url': playlist_url,
                'download_id': download_id if 'download_id' in locals() else None
            }
            
            logger.error(f"Playlist download failed for {playlist_url}: {e}")
            return error_result
    
    def _download_playlist_with_ytdlp(self, url: str, ydl_opts: Dict) -> Dict[str, Any]:
        """
        Execute playlist download in synchronous context.
        """
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
                return {
                    'status': 'success',
                    'action': 'playlist_downloaded',
                    'playlist_url': url
                }
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e),
                'playlist_url': url
            }
    
    async def extract_info(self, url: str, **kwargs) -> Dict[str, Any]:
        """
        Extract video/playlist information without downloading.
        
        Args:
            url: Video or playlist URL
            **kwargs: Additional yt-dlp options
            
        Returns:
            Dict containing extracted information
        """
        return await self.download_video(
            url, 
            extract_info_only=True,
            **kwargs
        )
    
    async def search_videos(self, 
                          query: str,
                          platform: str = "youtube",
                          max_results: int = 10,
                          **kwargs) -> Dict[str, Any]:
        """
        Search for videos on specified platform.
        
        Args:
            query: Search query
            platform: Platform to search on
            max_results: Maximum number of results
            **kwargs: Additional search options
            
        Returns:
            Dict containing search results
        """
        try:
            # Build search URL based on platform
            if platform.lower() == "youtube":
                search_url = f"ytsearch{max_results}:{query}"
            elif platform.lower() == "soundcloud":
                search_url = f"scsearch{max_results}:{query}"
            else:
                return {
                    'status': 'error',
                    'error': f"Platform '{platform}' not supported for search"
                }
            
            # Extract info for search results
            result = await self.extract_info(search_url, **kwargs)
            
            if result['status'] == 'success' and 'info' in result:
                entries = result['info'].get('entries', [])
                search_results = []
                
                for entry in entries:
                    search_results.append({
                        'title': entry.get('title'),
                        'url': entry.get('webpage_url'),
                        'duration': entry.get('duration'),
                        'uploader': entry.get('uploader'),
                        'view_count': entry.get('view_count'),
                        'upload_date': entry.get('upload_date'),
                        'description': entry.get('description', '')[:200] + '...' if entry.get('description') else ''
                    })
                
                return {
                    'status': 'success',
                    'query': query,
                    'platform': platform,
                    'results': search_results,
                    'total_results': len(search_results)
                }
            else:
                return result
                
        except Exception as e:
            logger.error(f"Search failed for query '{query}': {e}")
            return {
                'status': 'error',
                'error': str(e),
                'query': query,
                'platform': platform
            }
    
    def get_download_status(self, download_id: str) -> Dict[str, Any]:
        """
        Get status of a specific download.
        
        Args:
            download_id: Download ID to check
            
        Returns:
            Dict containing download status
        """
        if download_id in self.downloads:
            download_info = self.downloads[download_id].copy()
            
            # Calculate duration if completed
            if 'end_time' in download_info:
                download_info['duration'] = download_info['end_time'] - download_info['start_time']
            
            return {
                'status': 'success',
                'download_id': download_id,
                'download_info': download_info
            }
        else:
            return {
                'status': 'error',
                'error': f"Download ID '{download_id}' not found"
            }
    
    def list_active_downloads(self) -> Dict[str, Any]:
        """
        List all tracked downloads.
        
        Returns:
            Dict containing all download information
        """
        active_downloads = []
        completed_downloads = []
        failed_downloads = []
        
        for download_id, info in self.downloads.items():
            download_info = info.copy()
            download_info['download_id'] = download_id
            
            if info['status'] == 'starting' or info['status'] == 'downloading':
                active_downloads.append(download_info)
            elif info['status'] == 'completed':
                completed_downloads.append(download_info)
            elif info['status'] == 'failed':
                failed_downloads.append(download_info)
        
        return {
            'status': 'success',
            'active_downloads': active_downloads,
            'completed_downloads': completed_downloads,
            'failed_downloads': failed_downloads,
            'total_active': len(active_downloads),
            'total_completed': len(completed_downloads),
            'total_failed': len(failed_downloads)
        }
    
    async def batch_download(self,
                           urls: List[str],
                           output_dir: Optional[str] = None,
                           quality: Optional[str] = None,
                           max_concurrent: int = 3,
                           progress_callback: Optional[Callable] = None,
                           **kwargs) -> Dict[str, Any]:
        """
        Download multiple URLs concurrently.
        
        Args:
            urls: List of URLs to download
            output_dir: Output directory for all downloads
            quality: Quality setting for all downloads
            max_concurrent: Maximum concurrent downloads
            progress_callback: Progress callback function
            **kwargs: Additional yt-dlp options
            
        Returns:
            Dict containing batch download results
        """
        try:
            batch_id = str(uuid.uuid4())
            semaphore = asyncio.Semaphore(max_concurrent)
            
            async def download_with_semaphore(url):
                async with semaphore:
                    return await self.download_video(
                        url,
                        output_path=str(Path(output_dir or self.default_output_dir) / f"{hash(url)}.%(ext)s") if output_dir else None,
                        quality=quality,
                        progress_callback=progress_callback,
                        **kwargs
                    )
            
            # Execute all downloads concurrently
            results = await asyncio.gather(
                *[download_with_semaphore(url) for url in urls],
                return_exceptions=True
            )
            
            # Process results
            successful_downloads = []
            failed_downloads = []
            
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    failed_downloads.append({
                        'url': urls[i],
                        'error': str(result)
                    })
                elif result.get('status') == 'success':
                    successful_downloads.append(result)
                else:
                    failed_downloads.append(result)
            
            return {
                'status': 'success',
                'batch_id': batch_id,
                'total_urls': len(urls),
                'successful_downloads': successful_downloads,
                'failed_downloads': failed_downloads,
                'success_count': len(successful_downloads),
                'failure_count': len(failed_downloads),
                'success_rate': len(successful_downloads) / len(urls) if urls else 0
            }
            
        except Exception as e:
            logger.error(f"Batch download failed: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'batch_id': batch_id if 'batch_id' in locals() else None,
                'total_urls': len(urls)
            }
    
    def cleanup_downloads(self, max_age_hours: int = 24) -> Dict[str, Any]:
        """
        Clean up old download tracking data.
        
        Args:
            max_age_hours: Maximum age in hours for keeping download data
            
        Returns:
            Dict containing cleanup results
        """
        try:
            current_time = time.time()
            max_age_seconds = max_age_hours * 3600
            
            downloads_to_remove = []
            for download_id, info in self.downloads.items():
                age = current_time - info['start_time']
                if age > max_age_seconds:
                    downloads_to_remove.append(download_id)
            
            # Remove old downloads
            for download_id in downloads_to_remove:
                del self.downloads[download_id]
            
            return {
                'status': 'success',
                'removed_downloads': len(downloads_to_remove),
                'remaining_downloads': len(self.downloads)
            }
            
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }
