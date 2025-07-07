# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/multimedia/ytdlp_wrapper.py'

Files last updated: 1751408933.7764564

Stub file last updated: 2025-07-07 02:00:56

## YtDlpWrapper

```python
class YtDlpWrapper:
    """
    Wrapper class for yt-dlp functionality with async support and enhanced features.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, default_output_dir: Optional[str] = None, enable_logging: bool = True, default_quality: str = "best"):
    """
    Initialize YT-DLP wrapper.

Args:
    default_output_dir: Default directory for downloads
    enable_logging: Enable detailed logging
    default_quality: Default quality setting
    """
```
* **Async:** False
* **Method:** True
* **Class:** YtDlpWrapper

## _download_playlist_with_ytdlp

```python
def _download_playlist_with_ytdlp(self, url: str, ydl_opts: Dict) -> Dict[str, Any]:
    """
    Execute playlist download in synchronous context.
    """
```
* **Async:** False
* **Method:** True
* **Class:** YtDlpWrapper

## _download_with_ytdlp

```python
def _download_with_ytdlp(self, url: str, ydl_opts: Dict, extract_only: bool) -> Dict[str, Any]:
    """
    Execute yt-dlp download in synchronous context.
    """
```
* **Async:** False
* **Method:** True
* **Class:** YtDlpWrapper

## batch_download

```python
async def batch_download(self, urls: List[str], output_dir: Optional[str] = None, quality: Optional[str] = None, max_concurrent: int = 3, progress_callback: Optional[Callable] = None, **kwargs) -> Dict[str, Any]:
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
```
* **Async:** True
* **Method:** True
* **Class:** YtDlpWrapper

## cleanup_downloads

```python
def cleanup_downloads(self, max_age_hours: int = 24) -> Dict[str, Any]:
    """
    Clean up old download tracking data.

Args:
    max_age_hours: Maximum age in hours for keeping download data
    
Returns:
    Dict containing cleanup results
    """
```
* **Async:** False
* **Method:** True
* **Class:** YtDlpWrapper

## download_playlist

```python
async def download_playlist(self, playlist_url: str, output_dir: Optional[str] = None, max_downloads: Optional[int] = None, quality: Optional[str] = None, progress_callback: Optional[Callable] = None, **kwargs) -> Dict[str, Any]:
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
```
* **Async:** True
* **Method:** True
* **Class:** YtDlpWrapper

## download_video

```python
async def download_video(self, url: str, output_path: Optional[str] = None, quality: Optional[str] = None, format_selector: Optional[str] = None, audio_only: bool = False, extract_info_only: bool = False, progress_callback: Optional[Callable] = None, **kwargs) -> Dict[str, Any]:
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
```
* **Async:** True
* **Method:** True
* **Class:** YtDlpWrapper

## download_with_semaphore

```python
async def download_with_semaphore(url):
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## extract_info

```python
async def extract_info(self, url: str, **kwargs) -> Dict[str, Any]:
    """
    Extract video/playlist information without downloading.

Args:
    url: Video or playlist URL
    **kwargs: Additional yt-dlp options
    
Returns:
    Dict containing extracted information
    """
```
* **Async:** True
* **Method:** True
* **Class:** YtDlpWrapper

## get_download_status

```python
def get_download_status(self, download_id: str) -> Dict[str, Any]:
    """
    Get status of a specific download.

Args:
    download_id: Download ID to check
    
Returns:
    Dict containing download status
    """
```
* **Async:** False
* **Method:** True
* **Class:** YtDlpWrapper

## list_active_downloads

```python
def list_active_downloads(self) -> Dict[str, Any]:
    """
    List all tracked downloads.

Returns:
    Dict containing all download information
    """
```
* **Async:** False
* **Method:** True
* **Class:** YtDlpWrapper

## playlist_progress_hook

```python
def playlist_progress_hook(d):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## progress_hook

```python
def progress_hook(d):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## search_videos

```python
async def search_videos(self, query: str, platform: str = "youtube", max_results: int = 10, **kwargs) -> Dict[str, Any]:
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
```
* **Async:** True
* **Method:** True
* **Class:** YtDlpWrapper
