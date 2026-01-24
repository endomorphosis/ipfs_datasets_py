# ipfs_datasets_py/mcp_server/tools/media_tools/ytdlp_download.py
"""
YT-DLP download tool for the MCP server.

This tool provides comprehensive video and audio downloading capabilities from
various platforms using yt-dlp, supporting single videos, playlists, and batch operations.
"""
import anyio
from typing import Dict, Any, Optional, Union, List
from pathlib import Path

from ipfs_datasets_py.mcp_server.logger import logger
from ipfs_datasets_py.multimedia import YtDlpWrapper, HAVE_YTDLP


async def ytdlp_download_video(
    url: Union[str, List[str]],
    output_dir: Optional[str] = None,
    quality: str = "best",
    format_selector: Optional[str] = None,
    audio_only: bool = False,
    extract_audio: bool = False,
    audio_format: str = "mp3",
    subtitle_langs: Optional[List[str]] = None,
    download_thumbnails: bool = False,
    download_info_json: bool = True,
    custom_opts: Optional[Dict[str, Any]] = None,
    timeout: int = 600
) -> Dict[str, Any]:
    """
    Download video(s) from various platforms using yt-dlp.
    
    Args:
        url: Video URL(s) to download
        output_dir: Output directory for downloads
        quality: Quality preference (best, worst, or specific format)
        format_selector: Custom format selector string
        audio_only: Download audio only
        extract_audio: Extract audio from video
        audio_format: Audio format for extraction (mp3, flac, wav, etc.)
        subtitle_langs: List of subtitle languages to download
        download_thumbnails: Download video thumbnails
        download_info_json: Download video metadata as JSON
        custom_opts: Additional yt-dlp options
        timeout: Download timeout in seconds
        
    Returns:
        Dict containing download results and metadata
    """
    try:
        if not HAVE_YTDLP:
            return {
                "status": "error",
                "error": "yt-dlp not available. Install with: pip install yt-dlp",
                "tool": "ytdlp_download_video"
            }
        
        # Handle multiple URLs
        urls = url if isinstance(url, list) else [url]
        
        # Validate URLs
        if not urls or not all(isinstance(u, str) and u.strip() for u in urls):
            return {
                "status": "error",
                "error": "Invalid URL(s) provided",
                "urls": urls
            }
        
        # Initialize wrapper
        wrapper = YtDlpWrapper(
            default_output_dir=output_dir,
            default_quality=quality
        )
        
        results = []
        for video_url in urls:
            try:
                logger.info(f"Downloading video from: {video_url}")
                
                # Prepare download options
                download_opts = {
                    "format_selector": format_selector,
                    "audio_only": audio_only,
                    "extract_audio": extract_audio,
                    "audio_format": audio_format,
                    "subtitle_langs": subtitle_langs,
                    "download_thumbnails": download_thumbnails,
                    "download_info_json": download_info_json,
                    "timeout": timeout
                }
                
                # Add custom options
                if custom_opts:
                    download_opts.update(custom_opts)
                
                # Download video
                result = await wrapper.download_video(video_url, **download_opts)
                results.append(result)
                
            except Exception as e:
                logger.error(f"Error downloading {video_url}: {e}")
                results.append({
                    "status": "error",
                    "error": str(e),
                    "url": video_url
                })
        
        # Aggregate results
        successful = [r for r in results if r.get("status") == "success"]
        failed = [r for r in results if r.get("status") != "success"]
        
        return {
            "status": "success" if successful else "error",
            "message": f"Downloaded {len(successful)} of {len(urls)} videos",
            "total_requested": len(urls),
            "successful_downloads": len(successful),
            "failed_downloads": len(failed),
            "results": results,
            "successful_results": successful,
            "failed_results": failed,
            "tool": "ytdlp_download_video"
        }
        
    except Exception as e:
        logger.error(f"Error in ytdlp_download_video: {e}")
        return {
            "status": "error",
            "error": str(e),
            "tool": "ytdlp_download_video",
            "urls": url
        }


async def ytdlp_download_playlist(
    playlist_url: str,
    output_dir: Optional[str] = None,
    quality: str = "best",
    max_downloads: Optional[int] = None,
    start_index: int = 1,
    end_index: Optional[int] = None,
    download_archive: Optional[str] = None,
    custom_opts: Optional[Dict[str, Any]] = None,
    timeout: int = 1200
) -> Dict[str, Any]:
    """
    Download entire playlist from various platforms.
    
    Args:
        playlist_url: Playlist URL to download
        output_dir: Output directory for downloads
        quality: Quality preference for all videos
        max_downloads: Maximum number of videos to download
        start_index: Start downloading from this index (1-based)
        end_index: Stop downloading at this index (1-based)
        download_archive: File to record downloaded videos
        custom_opts: Additional yt-dlp options
        timeout: Total download timeout in seconds
        
    Returns:
        Dict containing playlist download results
    """
    try:
        if not HAVE_YTDLP:
            return {
                "status": "error",
                "error": "yt-dlp not available. Install with: pip install yt-dlp",
                "tool": "ytdlp_download_playlist"
            }
        
        if not playlist_url or not isinstance(playlist_url, str):
            return {
                "status": "error",
                "error": "Invalid playlist URL provided",
                "playlist_url": playlist_url
            }
        
        # Initialize wrapper
        wrapper = YtDlpWrapper(
            default_output_dir=output_dir,
            default_quality=quality
        )
        
        logger.info(f"Downloading playlist: {playlist_url}")
        
        # Prepare playlist options
        playlist_opts = {
            "max_downloads": max_downloads,
            "start_index": start_index,
            "end_index": end_index,
            "download_archive": download_archive,
            "timeout": timeout
        }
        
        # Add custom options
        if custom_opts:
            playlist_opts.update(custom_opts)
        
        # Download playlist
        result = await wrapper.download_playlist(playlist_url, **playlist_opts)
        
        return {
            **result,
            "tool": "ytdlp_download_playlist"
        }
        
    except Exception as e:
        logger.error(f"Error in ytdlp_download_playlist: {e}")
        return {
            "status": "error",
            "error": str(e),
            "tool": "ytdlp_download_playlist",
            "playlist_url": playlist_url
        }


async def ytdlp_extract_info(
    url: str,
    download: bool = False,
    extract_flat: bool = False,
    include_subtitles: bool = False,
    include_thumbnails: bool = False
) -> Dict[str, Any]:
    """
    Extract video/playlist information without downloading.
    
    Args:
        url: Video or playlist URL
        download: Whether to download the video
        extract_flat: Extract flat playlist info (faster for large playlists)
        include_subtitles: Include subtitle information
        include_thumbnails: Include thumbnail information
        
    Returns:
        Dict containing video/playlist metadata
    """
    try:
        if not HAVE_YTDLP:
            return {
                "status": "error",
                "error": "yt-dlp not available. Install with: pip install yt-dlp",
                "tool": "ytdlp_extract_info"
            }
        
        if not url or not isinstance(url, str):
            return {
                "status": "error",
                "error": "Invalid URL provided",
                "url": url
            }
        
        # Initialize wrapper
        wrapper = YtDlpWrapper()
        
        logger.info(f"Extracting info for: {url}")
        
        # Extract information
        result = await wrapper.extract_info(
            url,
            download=download,
            extract_flat=extract_flat,
            include_subtitles=include_subtitles,
            include_thumbnails=include_thumbnails
        )
        
        return {
            **result,
            "tool": "ytdlp_extract_info"
        }
        
    except Exception as e:
        logger.error(f"Error in ytdlp_extract_info: {e}")
        return {
            "status": "error",
            "error": str(e),
            "tool": "ytdlp_extract_info",
            "url": url
        }


async def ytdlp_search_videos(
    query: str,
    max_results: int = 10,
    search_type: str = "ytsearch",
    extract_info: bool = True
) -> Dict[str, Any]:
    """
    Search for videos on various platforms.
    
    Args:
        query: Search query string
        max_results: Maximum number of results to return
        search_type: Search type (ytsearch, ytsearchall, etc.)
        extract_info: Extract detailed info for each result
        
    Returns:
        Dict containing search results
    """
    try:
        if not HAVE_YTDLP:
            return {
                "status": "error",
                "error": "yt-dlp not available. Install with: pip install yt-dlp",
                "tool": "ytdlp_search_videos"
            }
        
        if not query or not isinstance(query, str):
            return {
                "status": "error",
                "error": "Invalid search query provided",
                "query": query
            }
        
        # Initialize wrapper
        wrapper = YtDlpWrapper()
        
        logger.info(f"Searching videos: {query}")
        
        # Search videos
        result = await wrapper.search_videos(
            query=query,
            max_results=max_results,
            search_type=search_type,
            extract_info=extract_info
        )
        
        return {
            **result,
            "tool": "ytdlp_search_videos"
        }
        
    except Exception as e:
        logger.error(f"Error in ytdlp_search_videos: {e}")
        return {
            "status": "error",
            "error": str(e),
            "tool": "ytdlp_search_videos",
            "query": query
        }


async def ytdlp_batch_download(
    urls: List[str],
    output_dir: Optional[str] = None,
    quality: str = "best",
    concurrent_downloads: int = 3,
    ignore_errors: bool = True,
    custom_opts: Optional[Dict[str, Any]] = None,
    timeout: int = 1800
) -> Dict[str, Any]:
    """
    Download multiple videos concurrently.
    
    Args:
        urls: List of video URLs to download
        output_dir: Output directory for downloads
        quality: Quality preference for all videos
        concurrent_downloads: Number of concurrent downloads
        ignore_errors: Continue downloading if some videos fail
        custom_opts: Additional yt-dlp options
        timeout: Total timeout for all downloads
        
    Returns:
        Dict containing batch download results
    """
    try:
        if not HAVE_YTDLP:
            return {
                "status": "error",
                "error": "yt-dlp not available. Install with: pip install yt-dlp",
                "tool": "ytdlp_batch_download"
            }
        
        if not urls or not isinstance(urls, list):
            return {
                "status": "error",
                "error": "Invalid URLs list provided",
                "urls": urls
            }
        
        # Initialize wrapper
        wrapper = YtDlpWrapper(
            default_output_dir=output_dir,
            default_quality=quality
        )
        
        logger.info(f"Starting batch download of {len(urls)} videos")
        
        # Prepare batch options
        batch_opts = {
            "concurrent_downloads": concurrent_downloads,
            "ignore_errors": ignore_errors,
            "timeout": timeout
        }
        
        # Add custom options
        if custom_opts:
            batch_opts.update(custom_opts)
        
        # Start batch download
        result = await wrapper.batch_download(urls, **batch_opts)
        
        return {
            **result,
            "tool": "ytdlp_batch_download"
        }
        
    except Exception as e:
        logger.error(f"Error in ytdlp_batch_download: {e}")
        return {
            "status": "error",
            "error": str(e),
            "tool": "ytdlp_batch_download",
            "urls": urls
        }


# Async main function for MCP registration
async def main() -> Dict[str, Any]:
    """Main function for MCP tool registration."""
    return {
        "status": "success",
        "message": "YT-DLP download tools initialized",
        "tools": [
            "ytdlp_download_video",
            "ytdlp_download_playlist", 
            "ytdlp_extract_info",
            "ytdlp_search_videos",
            "ytdlp_batch_download"
        ],
        "description": "Download videos and audio from various platforms using yt-dlp",
        "ytdlp_available": HAVE_YTDLP,
        "supported_sites": "1000+ sites including YouTube, Vimeo, SoundCloud, etc."
    }


if __name__ == "__main__":
    # Example usage
    test_result = anyio.run(ytdlp_extract_info(
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        download=False
    ))
    print(f"Test result: {test_result}")
