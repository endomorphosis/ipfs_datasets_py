"""
YT-DLP Download Engine — canonical package module for video/audio downloading.

Contains pure Python logic for downloading videos, playlists, and batches using
the canonical YtDlpWrapper. The MCP tool at
mcp_server/tools/media_tools/ytdlp_download.py is a thin re-export shim.

Usage::

    from ipfs_datasets_py.processors.multimedia.ytdlp_download_engine import (
        ytdlp_download_video,
        ytdlp_download_playlist,
        ytdlp_extract_info,
        ytdlp_search_videos,
        ytdlp_batch_download,
    )
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union

from ipfs_datasets_py.processors.multimedia.ytdlp_wrapper import YtDlpWrapper

try:
    import yt_dlp  # noqa: F401
    HAVE_YTDLP = True
except ImportError:
    HAVE_YTDLP = False

logger = logging.getLogger(__name__)

_UNAVAILABLE = {
    "status": "error",
    "error": "yt-dlp not available. Install with: pip install yt-dlp",
}


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
    timeout: int = 600,
) -> Dict[str, Any]:
    """Download video(s) from various platforms using yt-dlp.

    Args:
        url: Video URL or list of URLs to download.
        output_dir: Output directory for downloaded files.
        quality: Quality preference (``"best"``, ``"worst"``, or a format string).
        format_selector: Custom yt-dlp format selector string.
        audio_only: If True, download audio stream only.
        extract_audio: If True, extract audio from video.
        audio_format: Audio format when ``extract_audio`` is True.
        subtitle_langs: Subtitle language codes to download.
        download_thumbnails: Download video thumbnails.
        download_info_json: Save video metadata as JSON.
        custom_opts: Extra yt-dlp options dict.
        timeout: Per-video download timeout in seconds.

    Returns:
        Dict with ``status``, ``successful_downloads``, ``failed_downloads``,
        ``results``, and aggregate counts.
    """
    if not HAVE_YTDLP:
        return {**_UNAVAILABLE, "tool": "ytdlp_download_video"}

    urls: List[str] = url if isinstance(url, list) else [url]
    if not urls or not all(isinstance(u, str) and u.strip() for u in urls):
        return {"status": "error", "error": "Invalid URL(s) provided", "urls": urls}

    wrapper = YtDlpWrapper(default_output_dir=output_dir, default_quality=quality)
    results: List[Dict[str, Any]] = []
    download_opts: Dict[str, Any] = {
        "format_selector": format_selector,
        "audio_only": audio_only,
        "extract_audio": extract_audio,
        "audio_format": audio_format,
        "subtitle_langs": subtitle_langs,
        "download_thumbnails": download_thumbnails,
        "download_info_json": download_info_json,
        "timeout": timeout,
        **(custom_opts or {}),
    }

    for video_url in urls:
        try:
            logger.info("Downloading video from: %s", video_url)
            res = await wrapper.download_video(video_url, **download_opts)
            results.append(res)
        except Exception as exc:
            logger.error("Error downloading %s: %s", video_url, exc)
            results.append({"status": "error", "error": str(exc), "url": video_url})

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
        "tool": "ytdlp_download_video",
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
    timeout: int = 1200,
) -> Dict[str, Any]:
    """Download an entire playlist from various platforms.

    Args:
        playlist_url: Playlist URL.
        output_dir: Output directory.
        quality: Quality preference.
        max_downloads: Maximum number of videos to download.
        start_index: 1-based start index.
        end_index: 1-based end index.
        download_archive: Path to yt-dlp download-archive file.
        custom_opts: Extra yt-dlp options.
        timeout: Total timeout in seconds.

    Returns:
        Dict with download results and metadata.
    """
    if not HAVE_YTDLP:
        return {**_UNAVAILABLE, "tool": "ytdlp_download_playlist"}

    if not playlist_url or not isinstance(playlist_url, str):
        return {"status": "error", "error": "Invalid playlist URL provided", "playlist_url": playlist_url}

    wrapper = YtDlpWrapper(default_output_dir=output_dir, default_quality=quality)
    playlist_opts: Dict[str, Any] = {
        "max_downloads": max_downloads,
        "start_index": start_index,
        "end_index": end_index,
        "download_archive": download_archive,
        "timeout": timeout,
        **(custom_opts or {}),
    }
    try:
        result = await wrapper.download_playlist(playlist_url, **playlist_opts)
        return {**result, "tool": "ytdlp_download_playlist"}
    except Exception as exc:
        logger.error("ytdlp_download_playlist failed: %s", exc)
        return {"status": "error", "error": str(exc), "tool": "ytdlp_download_playlist"}


async def ytdlp_extract_info(
    url: str,
    download: bool = False,
    extract_flat: bool = False,
    include_subtitles: bool = False,
    include_thumbnails: bool = False,
) -> Dict[str, Any]:
    """Extract video/playlist metadata without downloading.

    Args:
        url: Video or playlist URL.
        download: If True, also download the video.
        extract_flat: Faster flat extraction (skips video-level details).
        include_subtitles: Include subtitle language info.
        include_thumbnails: Include thumbnail URLs.

    Returns:
        Dict with video/playlist metadata.
    """
    if not HAVE_YTDLP:
        return {**_UNAVAILABLE, "tool": "ytdlp_extract_info"}

    if not url or not isinstance(url, str):
        return {"status": "error", "error": "Invalid URL provided", "url": url}

    wrapper = YtDlpWrapper()
    try:
        result = await wrapper.extract_info(
            url,
            download=download,
            extract_flat=extract_flat,
            include_subtitles=include_subtitles,
            include_thumbnails=include_thumbnails,
        )
        return {**result, "tool": "ytdlp_extract_info"}
    except Exception as exc:
        logger.error("ytdlp_extract_info failed: %s", exc)
        return {"status": "error", "error": str(exc), "tool": "ytdlp_extract_info"}


async def ytdlp_search_videos(
    query: str,
    max_results: int = 10,
    search_type: str = "ytsearch",
    extract_info: bool = True,
) -> Dict[str, Any]:
    """Search for videos on various platforms.

    Args:
        query: Search query string.
        max_results: Maximum number of results to return.
        search_type: Search provider prefix (e.g. ``"ytsearch"``).
        extract_info: Fetch detailed metadata for each result.

    Returns:
        Dict with search results.
    """
    if not HAVE_YTDLP:
        return {**_UNAVAILABLE, "tool": "ytdlp_search_videos"}

    if not query or not isinstance(query, str):
        return {"status": "error", "error": "Invalid search query provided", "query": query}

    wrapper = YtDlpWrapper()
    try:
        result = await wrapper.search_videos(
            query=query,
            max_results=max_results,
            search_type=search_type,
            extract_info=extract_info,
        )
        return {**result, "tool": "ytdlp_search_videos"}
    except Exception as exc:
        logger.error("ytdlp_search_videos failed: %s", exc)
        return {"status": "error", "error": str(exc), "tool": "ytdlp_search_videos"}


async def ytdlp_batch_download(
    urls: List[str],
    output_dir: Optional[str] = None,
    quality: str = "best",
    concurrent_downloads: int = 3,
    ignore_errors: bool = True,
    custom_opts: Optional[Dict[str, Any]] = None,
    timeout: int = 1800,
) -> Dict[str, Any]:
    """Download multiple videos concurrently.

    Args:
        urls: List of video URLs to download.
        output_dir: Output directory.
        quality: Quality preference.
        concurrent_downloads: Maximum simultaneous downloads.
        ignore_errors: Continue if individual downloads fail.
        custom_opts: Extra yt-dlp options.
        timeout: Total timeout for all downloads in seconds.

    Returns:
        Dict with batch download results.
    """
    if not HAVE_YTDLP:
        return {**_UNAVAILABLE, "tool": "ytdlp_batch_download"}

    if not urls or not isinstance(urls, list):
        return {"status": "error", "error": "Invalid URLs list provided", "urls": urls}

    wrapper = YtDlpWrapper(default_output_dir=output_dir, default_quality=quality)
    batch_opts: Dict[str, Any] = {
        "concurrent_downloads": concurrent_downloads,
        "ignore_errors": ignore_errors,
        "timeout": timeout,
        **(custom_opts or {}),
    }
    try:
        result = await wrapper.batch_download(urls, **batch_opts)
        return {**result, "tool": "ytdlp_batch_download"}
    except Exception as exc:
        logger.error("ytdlp_batch_download failed: %s", exc)
        return {"status": "error", "error": str(exc), "tool": "ytdlp_batch_download"}
