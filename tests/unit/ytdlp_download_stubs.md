# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/media_tools/ytdlp_download.py'

## main

```python
async def main() -> Dict[str, Any]:
    """
    Main function for MCP tool registration.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## ytdlp_batch_download

```python
async def ytdlp_batch_download(urls: List[str], output_dir: Optional[str] = None, quality: str = "best", concurrent_downloads: int = 3, ignore_errors: bool = True, custom_opts: Optional[Dict[str, Any]] = None, timeout: int = 1800) -> Dict[str, Any]:
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
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## ytdlp_download_playlist

```python
async def ytdlp_download_playlist(playlist_url: str, output_dir: Optional[str] = None, quality: str = "best", max_downloads: Optional[int] = None, start_index: int = 1, end_index: Optional[int] = None, download_archive: Optional[str] = None, custom_opts: Optional[Dict[str, Any]] = None, timeout: int = 1200) -> Dict[str, Any]:
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
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## ytdlp_download_video

```python
async def ytdlp_download_video(url: Union[str, List[str]], output_dir: Optional[str] = None, quality: str = "best", format_selector: Optional[str] = None, audio_only: bool = False, extract_audio: bool = False, audio_format: str = "mp3", subtitle_langs: Optional[List[str]] = None, download_thumbnails: bool = False, download_info_json: bool = True, custom_opts: Optional[Dict[str, Any]] = None, timeout: int = 600) -> Dict[str, Any]:
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
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## ytdlp_extract_info

```python
async def ytdlp_extract_info(url: str, download: bool = False, extract_flat: bool = False, include_subtitles: bool = False, include_thumbnails: bool = False) -> Dict[str, Any]:
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
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## ytdlp_search_videos

```python
async def ytdlp_search_videos(query: str, max_results: int = 10, search_type: str = "ytsearch", extract_info: bool = True) -> Dict[str, Any]:
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
```
* **Async:** True
* **Method:** False
* **Class:** N/A
