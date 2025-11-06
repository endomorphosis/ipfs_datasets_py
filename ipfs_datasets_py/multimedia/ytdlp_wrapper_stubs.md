# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/multimedia/ytdlp_wrapper.py'

Files last updated: 1752454079.511931

Stub file last updated: 2025-07-13 17:48:41

## YtDlpWrapper

```python
class YtDlpWrapper:
    """
    YT-DLP Wrapper for Multi-Platform Media Downloads

The YtDlpWrapper class provides a robust, asynchronous interface to yt-dlp for downloading
videos, audio, and playlists from YouTube, Vimeo, SoundCloud, and hundreds of other platforms.
It offers advanced features including concurrent downloads, progress tracking, metadata extraction,
search capabilities, and comprehensive error handling. The wrapper is designed for production use
with extensive logging, download state management, and flexible configuration options.

This class abstracts the complexity of yt-dlp while providing additional functionality such as
async/await support, batch processing, playlist management, and intelligent format selection.
It maintains download histories, provides detailed progress callbacks, and supports both
streaming and download-to-disk operations.

Args:
    default_output_dir (Optional[str], optional): Default directory path for downloaded files.
        If not provided, uses system temporary directory. The directory will be created
        if it doesn't exist. Defaults to None.
    enable_logging (bool, optional): Enable detailed logging output from yt-dlp operations.
        When True, provides verbose information about download progress and errors.
        When False, suppresses most yt-dlp warnings and status messages. Defaults to True.
    default_quality (str, optional): Default quality setting for video downloads.
        Supported values include 'best', 'worst', specific resolutions like '720p',
        or custom format selectors. Defaults to "best".

Key Features:
- Asynchronous download operations with asyncio support
- Multi-platform support (YouTube, Vimeo, SoundCloud, 800+ sites)
- Concurrent batch downloads with rate limiting
- Comprehensive progress tracking and callback system
- Playlist processing with selective download capabilities
- Audio extraction with format conversion support
- Search functionality across supported platforms
- Metadata extraction without downloading content
- Download state management and history tracking
- Intelligent error handling and recovery mechanisms
- FFMPEG integration for post-processing operations

Attributes:
    default_output_dir (Path): Default directory for downloaded files
    enable_logging (bool): Whether detailed logging is enabled
    default_quality (str): Default quality setting for downloads
    downloads (Dict[str, Dict[str, Any]]): Registry tracking all download operations,
        keyed by unique download IDs containing status, timing, and result information

Public Methods:
    download_video(url, output_path=None, quality=None, **kwargs) -> Dict[str, Any]:
        Download single video with comprehensive options for quality, format,
        audio extraction, and progress tracking.
    download_playlist(playlist_url, output_dir=None, max_downloads=None, **kwargs) -> Dict[str, Any]:
        Download complete playlists with selective item processing and
        organized output directory structure.
    extract_info(url, **kwargs) -> Dict[str, Any]:
        Extract comprehensive metadata without downloading content including
        title, duration, formats, uploader information, and view statistics.
    search_videos(query, platform="youtube", max_results=10, **kwargs) -> Dict[str, Any]:
        Search for videos on supported platforms with customizable result limits
        and platform-specific search capabilities.
    batch_download(urls, output_dir=None, max_concurrent=3, **kwargs) -> Dict[str, Any]:
        Download multiple URLs concurrently with semaphore-based rate limiting
        and comprehensive result aggregation.
    get_download_status(download_id) -> Dict[str, Any]:
        Retrieve detailed status information for specific download operations
        including timing, progress, and error details.
    list_active_downloads() -> Dict[str, Any]:
        Get comprehensive overview of all tracked downloads categorized by
        status (active, completed, failed).
    cleanup_downloads(max_age_hours=24) -> Dict[str, Any]:
        Remove old download tracking data based on configurable age thresholds
        to prevent memory accumulation.

Usage Examples:
    # Basic video download
    wrapper = YtDlpWrapper(default_output_dir="/downloads")
    result = await wrapper.download_video("https://youtube.com/watch?v=example")
    
    # Audio-only download with custom quality
    result = await wrapper.download_video(
        url="https://youtube.com/watch?v=example",
        audio_only=True,
        audio_codec="mp3",
        audio_quality="320"
    )
    
    # Playlist download with limits
    result = await wrapper.download_playlist(
        "https://youtube.com/playlist?list=example",
        max_downloads=10,
        quality="720p"
    )
    
    # Batch download with progress tracking
    def progress_callback(download_id, progress_data):
        print(f"Download {download_id}: {progress_data}")
    
    urls = ["https://youtube.com/watch?v=1", "https://youtube.com/watch?v=2"]
    result = await wrapper.batch_download(
        urls,
        max_concurrent=2,
        progress_callback=progress_callback
    )
    
    # Search and download
    search_results = await wrapper.search_videos("python tutorial", max_results=5)
    for video in search_results['results']:
        await wrapper.download_video(video['url'])

Dependencies:
    - yt-dlp: Core download functionality (required)
    - asyncio: Asynchronous operation support
    - pathlib: Cross-platform path handling
    - uuid: Unique download ID generation
    - logging: Comprehensive logging support

Notes:
    - Requires yt-dlp package installation: pip install yt-dlp
    - FFMPEG recommended for audio extraction and format conversion
    - Download tracking data accumulates in memory and should be cleaned periodically
    - Progress callbacks receive download_id and yt-dlp progress dictionaries
    - All methods return standardized result dictionaries with 'status' field
    - Error handling preserves original yt-dlp error information
    - Concurrent downloads are limited to prevent resource exhaustion
    - Playlist downloads create subdirectories based on playlist names
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, default_output_dir: Optional[str] = None, enable_logging: bool = True, default_quality: str = "best"):
    """
    Initialize YT-DLP wrapper with configuration options and dependency validation.

Sets up the wrapper instance with specified output directory, logging preferences,
and default quality settings. Validates yt-dlp availability and initializes
internal tracking structures for download management.

Args:
    default_output_dir (Optional[str], optional): Default directory path for downloaded files.
        If not provided, uses system temporary directory from tempfile.gettempdir().
        The directory will be created automatically if it doesn't exist. Path can be
        absolute or relative. Defaults to None.
    enable_logging (bool, optional): Enable detailed logging output from yt-dlp operations.
        When True, provides verbose information about download progress, format selection,
        and extraction details. When False, suppresses most yt-dlp warnings and status
        messages for cleaner output. Defaults to True.
    default_quality (str, optional): Default quality setting for video downloads when
        not explicitly specified. Supported values include:
        - 'best': Highest available quality
        - 'worst': Lowest available quality  
        - Resolution strings: '720p', '1080p', '480p'
        - Custom format selectors: 'best[height<=720]'
        Defaults to "best".

Attributes initialized:
    default_output_dir (Path): Path object for default download directory, created
        from provided string or system temp directory.
    enable_logging (bool): Boolean flag controlling yt-dlp logging verbosity.
    default_quality (str): Default quality setting for download operations.
    downloads (Dict[str, Dict[str, Any]]): Empty dictionary for tracking download
        operations, keyed by UUID strings with values containing status, timing,
        URL, output directory, and result information.

Raises:
    ImportError: If yt-dlp package is not installed or cannot be imported.
        Includes installation instructions in error message.

Examples:
    >>> # Basic initialization with defaults
    >>> wrapper = YtDlpWrapper()
    
    >>> # Custom output directory with quiet logging
    >>> wrapper = YtDlpWrapper(
    ...     default_output_dir="/home/user/downloads",
    ...     enable_logging=False,
    ...     default_quality="720p"
    ... )
    
    >>> # Production configuration
    >>> wrapper = YtDlpWrapper(
    ...     default_output_dir="/var/media/downloads",
    ...     enable_logging=True,
    ...     default_quality="best[height<=1080]"
    ... )

Notes:
    - The default output directory is created immediately if it doesn't exist
    - yt-dlp availability is checked during initialization, not at method call time
    - Download tracking dictionary starts empty and accumulates data over time
    - All paths are converted to Path objects for cross-platform compatibility
    """
```
* **Async:** False
* **Method:** True
* **Class:** YtDlpWrapper


## batch_download

```python
async def batch_download(self, urls: List[str], output_dir: Optional[str] = None, quality: Optional[str] = None, max_concurrent: int = 3, progress_callback: Optional[Callable] = None, **kwargs) -> Dict[str, Any]:
    """
    Download multiple URLs concurrently with semaphore-based rate limiting and result aggregation.

This method enables efficient parallel downloading of multiple videos with configurable
concurrency limits to prevent resource exhaustion. It provides comprehensive result
tracking for both successful and failed downloads with detailed statistics and
individual download information.

Args:
    urls (List[str]): List of video URLs to download concurrently. Each URL should be
        from a yt-dlp supported platform. Empty list returns immediately with success.
        Duplicate URLs are processed independently.
    output_dir (Optional[str], optional): Base output directory for all downloads.
        If provided, each download gets a unique filename based on URL hash to prevent
        conflicts. If None, uses default_output_dir. Defaults to None.
    quality (Optional[str], optional): Quality setting applied to all downloads.
        Same format as download_video quality parameter. Examples: 'best', '720p',
        'best[height<=1080]'. Defaults to None (uses instance default).
    max_concurrent (int, optional): Maximum number of simultaneous downloads.
        Higher values increase speed but consume more resources. Recommended range: 1-10.
        Must be positive integer. Defaults to 3.
    progress_callback (Optional[Callable], optional): Callback function for individual
        download progress. Function signature: callback(download_id: str, progress_data: Dict).
        Called for each download's progress updates. Defaults to None.
    **kwargs: Additional yt-dlp options applied to all downloads.
        Common batch options:
        - audio_only (bool): Extract audio from all videos
        - writesubtitles (bool): Download subtitles for all videos
        - format_selector (str): Custom format selector for all

Returns:
    Dict[str, Any]: Comprehensive batch download results containing:
        - status (str): Always 'success' (individual failures don't affect batch status)
        - batch_id (str): Unique identifier for this batch operation
        - total_urls (int): Total number of URLs processed
        - successful_downloads (List[Dict[str, Any]]): List of successful download results,
          each containing the complete download_video return dictionary
        - failed_downloads (List[Dict[str, Any]]): List of failed downloads with:
          - url (str): Original URL that failed
          - error (str): Error message or exception details
        - success_count (int): Number of successful downloads
        - failure_count (int): Number of failed downloads  
        - success_rate (float): Ratio of successful to total downloads (0.0-1.0)

Raises:
    ValueError: If max_concurrent is not a positive integer
    TypeError: If urls is not a list or contains non-string elements,
        or if progress_callback is not callable

Examples:
    >>> # Basic batch download
    >>> urls = [
    ...     "https://youtube.com/watch?v=video1",
    ...     "https://youtube.com/watch?v=video2", 
    ...     "https://youtube.com/watch?v=video3"
    ... ]
    >>> result = await wrapper.batch_download(urls)
    >>> print(f"Success rate: {result['success_rate']:.1%}")
    >>> print(f"Downloaded {result['success_count']}/{result['total_urls']} videos")
    
    >>> # High-quality batch with custom concurrency
    >>> result = await wrapper.batch_download(
    ...     urls=video_urls,
    ...     output_dir="/downloads/batch_2024",
    ...     quality="best[height<=1080]",
    ...     max_concurrent=5
    ... )
    
    >>> # Audio extraction batch
    >>> result = await wrapper.batch_download(
    ...     urls=music_urls,
    ...     audio_only=True,
    ...     audio_codec="mp3",
    ...     audio_quality="320",
    ...     max_concurrent=2
    ... )
    
    >>> # Progress monitoring for large batches
    >>> def batch_progress(download_id, progress):
    ...     if progress.get('status') == 'downloading':
    ...         percent = progress.get('_percent_str', 'N/A')
    ...         speed = progress.get('_speed_str', 'N/A')
    ...         print(f"{download_id}: {percent} at {speed}")
    >>> 
    >>> result = await wrapper.batch_download(
    ...     urls=large_url_list,
    ...     progress_callback=batch_progress,
    ...     max_concurrent=4
    ... )
    
    >>> # Handle failures in batch results
    >>> result = await wrapper.batch_download(urls)
    >>> if result['failed_downloads']:
    ...     print("Failed downloads:")
    ...     for failure in result['failed_downloads']:
    ...         print(f"  {failure['url']}: {failure['error']}")
    ...     
    ...     # Retry failed downloads
    ...     failed_urls = [f['url'] for f in result['failed_downloads']]
    ...     retry_result = await wrapper.batch_download(failed_urls, max_concurrent=1)

Notes:
    - Individual download failures don't stop the batch operation
    - Each download gets a unique output filename to prevent conflicts
    - Progress callbacks are called for each individual download
    - All downloads are tracked individually in the downloads registry
    """
```
* **Async:** True
* **Method:** True
* **Class:** YtDlpWrapper

## cleanup_downloads

```python
def cleanup_downloads(self, max_age_hours: int = 24) -> Dict[str, Any]:
    """
    Remove old download tracking data based on configurable age thresholds.

This method manages memory usage by removing download tracking records older than
the specified age limit. It's essential for long-running applications that process
many downloads to prevent unlimited memory accumulation while preserving recent
download history for monitoring and debugging.

Args:
    max_age_hours (int, optional): Maximum age in hours for keeping download tracking data.
        Downloads older than this threshold are removed from internal tracking.
        Must be non-negative integer. Value of 0 removes all completed downloads.
        Defaults to 24.

Returns:
    Dict[str, Any]: Cleanup operation results containing:
        - status (str): 'success' for normal operation, 'error' if exception occurred
        - removed_downloads (int): Number of download records removed
        - remaining_downloads (int): Number of download records still tracked
        For errors:
        - error (str): Detailed error message

Raises:
    ValueError: If max_age_hours is negative
    TypeError: If max_age_hours is not an integer

Examples:
    >>> # Daily cleanup (default)
    >>> result = wrapper.cleanup_downloads()
    >>> print(f"Removed {result['removed_downloads']} old downloads")
    >>> print(f"{result['remaining_downloads']} downloads still tracked")
    
    >>> # Aggressive cleanup - remove downloads older than 1 hour
    >>> result = wrapper.cleanup_downloads(max_age_hours=1)
    
    >>> # Remove all completed downloads
    >>> result = wrapper.cleanup_downloads(max_age_hours=0)
    
    >>> # Scheduled cleanup in long-running application
    >>> import asyncio
    >>> 
    >>> async def periodic_cleanup():
    ...     while True:
    ...         await asyncio.sleep(3600)  # Every hour
    ...         result = wrapper.cleanup_downloads(max_age_hours=6)
    ...         if result['removed_downloads'] > 0:
    ...             print(f"Cleaned up {result['removed_downloads']} downloads")
    >>> 
    >>> # Start cleanup task
    >>> asyncio.create_task(periodic_cleanup())
    
    >>> # Conditional cleanup based on memory usage
    >>> overview = wrapper.list_active_downloads()
    >>> total_tracked = (overview['total_active'] + 
    ...                 overview['total_completed'] + 
    ...                 overview['total_failed'])
    >>> 
    >>> if total_tracked > 1000:
    ...     # Remove downloads older than 2 hours
    ...     cleanup_result = wrapper.cleanup_downloads(max_age_hours=2)
    ...     print(f"Memory cleanup: removed {cleanup_result['removed_downloads']} records")

Notes:
    - Only removes tracking data, not downloaded files
    - Active downloads (status 'starting' or 'downloading') are never removed
    - Age calculation based on start_time of download operation
    - Cleanup is immediate and cannot be undone
    - Regular cleanup prevents memory leaks in long-running applications
    - Removed downloads cannot be queried with get_download_status()
    """
```
* **Async:** False
* **Method:** True
* **Class:** YtDlpWrapper

## download_playlist

```python
async def download_playlist(self, playlist_url: str, output_dir: Optional[str] = None, max_downloads: Optional[int] = None, quality: Optional[str] = None, progress_callback: Optional[Callable] = None, **kwargs) -> Dict[str, Any]:
    """
    Download complete playlists with selective item processing and organized output structure.

This method processes YouTube playlists, SoundCloud sets, and other platform collections
with comprehensive control over download limits, quality settings, and output organization.
It provides detailed progress tracking for individual items and overall playlist completion
with robust error handling for partial failures.

Args:
    playlist_url (str): Valid playlist URL from any supported platform including:
        - YouTube playlists: https://youtube.com/playlist?list=PLAYLIST_ID
        - SoundCloud sets: https://soundcloud.com/user/sets/playlist-name
        - Vimeo showcases: https://vimeo.com/showcase/SHOWCASE_ID
        URL format validation is handled by yt-dlp.
    output_dir (Optional[str], optional): Custom output directory for playlist items.
        If not provided, uses default_output_dir. Creates subdirectory structure
        based on playlist name: output_dir/playlist_name/item_files.
        Defaults to None.
    max_downloads (Optional[int], optional): Maximum number of playlist items to download.
        Useful for testing or limiting large playlists. Uses yt-dlp's playlistend option.
        If None, downloads entire playlist. Must be positive integer. Defaults to None.
    quality (Optional[str], optional): Quality setting applied to all playlist items.
        Same format as download_video quality parameter. Overrides instance default_quality.
        Examples: 'best', 'worst', '720p', 'best[height<=1080]'. Defaults to None.
    progress_callback (Optional[Callable], optional): Callback function for progress updates.
        Function signature: callback(download_id: str, progress_data: Dict[str, Any]).
        Progress data includes individual item progress and overall playlist statistics:
        - downloaded (int): Number of successfully downloaded items
        - failed (int): Number of failed items
        - current (Dict): Current item's yt-dlp progress data
        Defaults to None.
    **kwargs: Additional yt-dlp options applied to all playlist items.
        Common playlist-specific options:
        - playliststart (int): Start downloading from specific index
        - playlistreverse (bool): Download in reverse order
        - writeinfojson (bool): Write info JSON for each item
        - extractaudio (bool): Extract audio from all items

Returns:
    Dict[str, Any]: Comprehensive playlist download result containing:
        - status (str): 'success' or 'error'
        - download_id (str): Unique identifier for this playlist operation
        - playlist_url (str): Original playlist URL
        - downloaded_items (List[str]): Paths to successfully downloaded files
        - failed_items (List[str]): Paths/names of items that failed to download
        - total_downloaded (int): Count of successful downloads
        - total_failed (int): Count of failed downloads
        - action (str): 'playlist_downloaded' for successful operations
        - error (str): Error message if status is 'error'

Raises:
    ValueError: If max_downloads is not a positive integer
    OSError: If output directory cannot be created or accessed
    PermissionError: If insufficient permissions for directory operations
    TypeError: If progress_callback is not callable

Examples:
    >>> # Basic playlist download
    >>> result = await wrapper.download_playlist(
    ...     "https://youtube.com/playlist?list=PLrAXtmRdnEQy6NumBgx-qF7kYnVQIgaqh"
    ... )
    >>> print(f"Downloaded {result['total_downloaded']} items")
    
    >>> # Limited playlist with custom quality
    >>> result = await wrapper.download_playlist(
    ...     playlist_url="https://youtube.com/playlist?list=example",
    ...     output_dir="/downloads/my_playlist",
    ...     max_downloads=10,
    ...     quality="720p"
    ... )
    
    >>> # Audio-only playlist extraction
    >>> result = await wrapper.download_playlist(
    ...     playlist_url="https://youtube.com/playlist?list=example",
    ...     extractaudio=True,
    ...     audioformat="mp3"
    ... )
    
    >>> # Progress tracking for large playlists
    >>> def playlist_progress(download_id, progress):
    ...     downloaded = progress.get('downloaded', 0)
    ...     failed = progress.get('failed', 0)
    ...     print(f"Playlist {download_id}: {downloaded} done, {failed} failed")
    >>> 
    >>> result = await wrapper.download_playlist(
    ...     playlist_url="https://youtube.com/playlist?list=large_playlist",
    ...     progress_callback=playlist_progress,
    ...     max_downloads=50
    ... )

Notes:
    - Playlist downloads create subdirectories named after the playlist
    - Individual item failures don't stop overall playlist processing
    - Progress callbacks are called after each item completion
    - Output template includes playlist name in directory structure
    - Download tracking persists for the entire playlist operation
    - Failed items are logged but don't raise exceptions
    """
```
* **Async:** True
* **Method:** True
* **Class:** YtDlpWrapper

## download_video

```python
async def download_video(self, url: str, output_path: Optional[str] = None, quality: Optional[str] = None, format_selector: Optional[str] = None, audio_only: bool = False, extract_info_only: bool = False, progress_callback: Optional[Callable] = None, **kwargs) -> Dict[str, Any]:
    """
    Download video from URL with comprehensive configuration options and progress tracking.

This method provides complete control over video downloading including quality selection,
format specification, audio extraction, and metadata-only operations. It supports
asynchronous execution with progress callbacks and maintains detailed download tracking
for status monitoring and error handling.

Args:
    url (str): Valid video URL from any yt-dlp supported platform including
        YouTube, Vimeo, SoundCloud, Twitch, and 800+ other sites.
        URL format validation is handled by yt-dlp.
    output_path (Optional[str], optional): Custom output file path including filename
        and extension. If provided, overrides default output directory and naming.
        Can include yt-dlp template variables like %(title)s, %(uploader)s.
        If None, uses default_output_dir with automatic naming. Defaults to None.
    quality (Optional[str], optional): Quality setting for video download.
        Overrides default_quality when specified. Supported values:
        - 'best': Highest available quality
        - 'worst': Lowest available quality
        - Resolution: '720p', '1080p', '480p', '4k'
        - Custom selectors: 'best[height<=720]', 'worst[ext=mp4]'
        Defaults to None (uses instance default_quality).
    format_selector (Optional[str], optional): Advanced yt-dlp format selector string
        for precise format control. Takes precedence over quality parameter.
        Examples: 'best[ext=mp4]', 'bestvideo+bestaudio/best'.
        Defaults to None.
    audio_only (bool, optional): Extract audio only, discarding video streams.
        When True, downloads best audio format and applies post-processing
        for format conversion. Defaults to False.
    extract_info_only (bool, optional): Extract metadata without downloading content.
        When True, returns comprehensive video information including title,
        duration, formats, thumbnails without downloading files. Defaults to False.
    progress_callback (Optional[Callable], optional): Callback function for progress updates.
        Function signature: callback(download_id: str, progress_data: Dict[str, Any]).
        Progress data contains yt-dlp progress dictionary with status, percentage,
        speed, ETA information. Defaults to None.
    **kwargs: Additional yt-dlp options passed directly to YoutubeDL constructor.
        Common options include:
        - audio_codec (str): Audio codec for conversion ('mp3', 'aac', 'flac')
        - audio_quality (str): Audio quality/bitrate ('192', '320', 'best')
        - writesubtitles (bool): Download subtitle files
        - writeinfojson (bool): Write video info JSON file
        - extractaudio (bool): Extract audio track

Returns:
    Dict[str, Any]: Comprehensive download result dictionary containing:
        - status (str): 'success', 'error', or operation-specific status
        - download_id (str): Unique identifier for tracking this download
        - action (str): Type of operation performed ('downloaded', 'info_extracted')
        - url (str): Original input URL
        - output_path (str): Path to downloaded file (if applicable)
        - info (Dict): yt-dlp extracted information dictionary
        - title (str): Video title (for info extraction)
        - duration (int): Video duration in seconds (for info extraction)
        - uploader (str): Channel/uploader name (for info extraction)
        - upload_date (str): Upload date in YYYYMMDD format (for info extraction)
        - view_count (int): View count number (for info extraction)
        - formats (List[Dict]): Available format list (for info extraction)
        - error (str): Error message (if status is 'error')

Raises:
    ImportError: If yt-dlp is not available (checked during initialization)
    OSError: If output directory cannot be created or accessed
    PermissionError: If insufficient permissions for file operations
    ValueError: If URL format is invalid or unsupported by yt-dlp
    TypeError: If progress_callback is not callable

Examples:
    >>> # Basic video download
    >>> result = await wrapper.download_video("https://youtube.com/watch?v=dQw4w9WgXcQ")
    >>> print(result['status'])  # 'success'
    >>> print(result['output_path'])  # Path to downloaded file
    
    >>> # High-quality download with custom path
    >>> result = await wrapper.download_video(
    ...     url="https://youtube.com/watch?v=example",
    ...     output_path="/downloads/%(title)s-%(upload_date)s.%(ext)s",
    ...     quality="best[height<=1080]"
    ... )
    
    >>> # Audio-only extraction
    >>> result = await wrapper.download_video(
    ...     url="https://youtube.com/watch?v=example",
    ...     audio_only=True,
    ...     audio_codec="mp3",
    ...     audio_quality="320"
    ... )
    
    >>> # Metadata extraction only
    >>> result = await wrapper.download_video(
    ...     url="https://youtube.com/watch?v=example",
    ...     extract_info_only=True
    ... )
    >>> print(result['title'])  # Video title
    >>> print(result['duration'])  # Duration in seconds
    
    >>> # Progress tracking
    >>> def progress_handler(download_id, progress):
    ...     if progress.get('status') == 'downloading':
    ...         percent = progress.get('_percent_str', 'N/A')
    ...         print(f"Download {download_id}: {percent}")
    >>> 
    >>> result = await wrapper.download_video(
    ...     url="https://youtube.com/watch?v=example",
    ...     progress_callback=progress_handler
    ... )

Notes:
    - Download operations are executed in thread pool to maintain async compatibility
    - Progress callbacks are called from yt-dlp hooks and may be frequent
    - Output directory is created automatically if it doesn't exist
    - Download tracking persists until cleanup_downloads() is called
    - Format selection precedence: format_selector > quality > default_quality
    - Audio extraction requires FFMPEG installation for format conversion
    - Error details preserve original yt-dlp exception information
    """
```
* **Async:** True
* **Method:** True
* **Class:** YtDlpWrapper

## download_with_semaphore

```python
async def _download_with_semaphore(url):
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## extract_info

```python
async def extract_info(self, url: str, **kwargs) -> Dict[str, Any]:
    """
    Extract comprehensive video/playlist metadata without downloading content.

This method provides fast metadata extraction for videos and playlists, returning
detailed information including formats, quality options, duration, thumbnails,
and platform-specific data. It's ideal for content analysis, format selection,
and building media catalogs without bandwidth costs.

Args:
    url (str): Video or playlist URL from any yt-dlp supported platform.
        Supports single videos, playlists, channels, and user pages.
    **kwargs: Additional yt-dlp options for extraction control.
        Common options include:
        - flat_playlist (bool): For playlists, only extract basic info per item
        - extract_flat (bool): Skip individual video info extraction
        - writeinfojson (bool): Also write info to JSON file

Returns:
    Dict[str, Any]: Extracted information dictionary with same format as
        download_video with extract_info_only=True. Contains comprehensive
        metadata without downloaded files.

Raises:
    ValueError: If URL format is invalid or unsupported
    ConnectionError: If network access fails during extraction
    PermissionError: If content is private or region-restricted

Examples:
    >>> # Extract video information
    >>> info = await wrapper.extract_info("https://youtube.com/watch?v=example")
    >>> print(f"Title: {info['title']}")
    >>> print(f"Duration: {info['duration']} seconds")
    >>> for fmt in info['formats']:
    ...     print(f"Format: {fmt['format_id']} - {fmt['ext']} - {fmt.get('height', 'audio')}p")
    
    >>> # Extract playlist metadata
    >>> info = await wrapper.extract_info("https://youtube.com/playlist?list=example")
    >>> print(f"Playlist has {len(info['info']['entries'])} items")

Notes:
    - Returns same format as download_video(..., extract_info_only=True)
    """
```
* **Async:** True
* **Method:** True
* **Class:** YtDlpWrapper

## get_download_status

```python
def get_download_status(self, download_id: str) -> Dict[str, Any]:
    """
    Retrieve detailed status and metadata for a specific download operation.

This method provides comprehensive information about download operations including
timing data, current status, result details, and error information. It's essential
for monitoring long-running downloads and debugging failed operations.

Args:
    download_id (str): Unique download identifier returned by download methods.
        Must be a valid UUID string from a previous download operation.

Returns:
    Dict[str, Any]: Download status dictionary containing:
        For found downloads:
        - status (str): 'success'
        - download_id (str): Confirmed download identifier
        - download_info (Dict[str, Any]): Complete download information:
          - url (str): Original download URL
          - status (str): Current status ('starting', 'downloading', 'completed', 'failed')
          - start_time (float): Unix timestamp when download started
          - end_time (float): Unix timestamp when download finished (if applicable)
          - duration (float): Total download time in seconds (if completed)
          - output_dir (str): Output directory path
          - type (str): Download type ('video', 'playlist', etc.)
          - result (Dict): Final download result (if completed)
          - error (str): Error message (if failed)
        
        For missing downloads:
        - status (str): 'error'
        - error (str): Error message indicating download not found

Raises:
    TypeError: If download_id is not a string
    
Examples:
    >>> # Start a download and monitor status
    >>> result = await wrapper.download_video("https://youtube.com/watch?v=example")
    >>> download_id = result['download_id']
    >>> 
    >>> # Check status later
    >>> status = wrapper.get_download_status(download_id)
    >>> if status['status'] == 'success':
    ...     info = status['download_info']
    ...     print(f"Download {info['status']}")
    ...     if 'duration' in info:
    ...         print(f"Took {info['duration']:.2f} seconds")
    
    >>> # Monitor multiple downloads
    >>> download_ids = []
    >>> for url in video_urls:
    ...     result = await wrapper.download_video(url)
    ...     download_ids.append(result['download_id'])
    >>> 
    >>> # Check all statuses
    >>> for did in download_ids:
    ...     status = wrapper.get_download_status(did)
    ...     if status['status'] == 'success':
    ...         info = status['download_info']
    ...         print(f"Download {did}: {info['status']}")

Notes:
    - Download tracking persists until cleanup_downloads() is called
    - Status information is updated in real-time during downloads
    - Duration is only available for completed or failed downloads
    - Result field contains the complete download method return value
    - Error field is only present for failed downloads
    - Download IDs are generated as UUID4 strings
    """
```
* **Async:** False
* **Method:** True
* **Class:** YtDlpWrapper

## list_active_downloads

```python
def list_active_downloads(self) -> Dict[str, Any]:
    """
    Retrieve comprehensive overview of all tracked download operations categorized by status.

This method provides a complete summary of download activity including active,
completed, and failed operations with counts and detailed information for each
category. It's essential for monitoring overall download queue status and
identifying issues across multiple operations.

Returns:
    Dict[str, Any]: Complete download overview dictionary containing:
        - status (str): Always 'success' for this method
        - active_downloads (List[Dict[str, Any]]): Currently running downloads:
          - download_id (str): Unique download identifier
          - url (str): Download URL
          - status (str): 'starting' or 'downloading'
          - start_time (float): Unix timestamp when started
          - output_dir (str): Output directory path
          - type (str): Download type ('video', 'playlist', etc.)
        - completed_downloads (List[Dict[str, Any]]): Successfully finished downloads:
          - download_id (str): Unique download identifier
          - url (str): Download URL  
          - status (str): 'completed'
          - start_time (float): Unix timestamp when started
          - end_time (float): Unix timestamp when completed
          - output_dir (str): Output directory path
          - result (Dict): Complete download result
        - failed_downloads (List[Dict[str, Any]]): Downloads that encountered errors:
          - download_id (str): Unique download identifier
          - url (str): Download URL
          - status (str): 'failed'
          - start_time (float): Unix timestamp when started
          - end_time (float): Unix timestamp when failed
          - error (str): Error message
        - total_active (int): Count of currently active downloads
        - total_completed (int): Count of successfully completed downloads  
        - total_failed (int): Count of failed downloads

Examples:
    >>> # Get overview of all downloads
    >>> overview = wrapper.list_active_downloads()
    >>> print(f"Active: {overview['total_active']}")
    >>> print(f"Completed: {overview['total_completed']}")
    >>> print(f"Failed: {overview['total_failed']}")
    
    >>> # Monitor active downloads
    >>> overview = wrapper.list_active_downloads()
    >>> for download in overview['active_downloads']:
    ...     elapsed = time.time() - download['start_time']
    ...     print(f"Download {download['download_id']}: {elapsed:.1f}s elapsed")
    
    >>> # Check for failures
    >>> overview = wrapper.list_active_downloads()
    >>> if overview['failed_downloads']:
    ...     print("Failed downloads:")
    ...     for download in overview['failed_downloads']:
    ...         print(f"  {download['url']}: {download['error']}")
    
    >>> # Cleanup old completed downloads
    >>> overview = wrapper.list_active_downloads()
    >>> if overview['total_completed'] > 100:
    ...     cleanup_result = wrapper.cleanup_downloads(max_age_hours=1)
    ...     print(f"Cleaned up {cleanup_result['removed_downloads']} old downloads")

Notes:
    - Download data accumulates until explicitly cleaned up
    - Status categorization is based on the 'status' field in download records
    - Each download appears in exactly one category
    - Download IDs are unique across all categories
    - Large numbers of tracked downloads may impact memory usage
    - Use cleanup_downloads() periodically to manage memory
    """
```
* **Async:** False
* **Method:** True
* **Class:** YtDlpWrapper

## search_videos

```python
async def search_videos(self, query: str, platform: str = "youtube", max_results: int = 10, **kwargs) -> Dict[str, Any]:
    """
    Search for videos on specified platforms with customizable result filtering.

This method provides integrated search capabilities for YouTube and SoundCloud,
returning structured results with metadata for each found video. It enables
content discovery and automated downloading based on search criteria without
requiring manual URL collection.

Args:
    query (str): Search query string. Supports platform-specific search operators
        and filters. Examples: "python tutorial", "music remix", "documentary 2024".
        Query is URL-encoded automatically.
    platform (str, optional): Platform to search on. Currently supported:
        - "youtube": YouTube video search using ytsearch prefix
        - "soundcloud": SoundCloud track search using scsearch prefix
        Case-insensitive. Defaults to "youtube".
    max_results (int, optional): Maximum number of search results to return.
        Must be positive integer. Large values may increase search time.
        Platform limits may apply. Defaults to 10.
    **kwargs: Additional yt-dlp search options passed to extract_info.
        Platform-specific options may be available.

Returns:
    Dict[str, Any]: Search results dictionary containing:
        For successful searches:
        - status (str): 'success'
        - query (str): Original search query
        - platform (str): Platform searched
        - results (List[Dict[str, Any]]): List of video metadata dictionaries:
          - title (str): Video title
          - url (str): Direct video URL for downloading
          - duration (int): Duration in seconds
          - uploader (str): Channel/artist name
          - view_count (int): View count number
          - upload_date (str): Upload date in YYYYMMDD format
          - description (str): Truncated description (first 200 chars)
        - total_results (int): Number of results returned
        
        For errors:
        - status (str): 'error'
        - error (str): Detailed error message
        - query (str): Original search query
        - platform (str): Platform attempted

Raises:
    ValueError: If max_results is not a positive integer
    ValueError: If platform is not supported
    ConnectionError: If network access fails during search
    TypeError: If query is not a string

Examples:
    >>> # Basic YouTube search
    >>> results = await wrapper.search_videos("python programming tutorial")
    >>> for video in results['results']:
    ...     print(f"{video['title']} - {video['duration']}s")
    ...     print(f"  URL: {video['url']}")
    
    >>> # SoundCloud music search
    >>> results = await wrapper.search_videos(
    ...     query="ambient electronic music",
    ...     platform="soundcloud",
    ...     max_results=20
    ... )
    
    >>> # Search and download top result
    >>> search_results = await wrapper.search_videos("best python course", max_results=1)
    >>> if search_results['results']:
    ...     top_video = search_results['results'][0]
    ...     download_result = await wrapper.download_video(top_video['url'])
    
    >>> # Search with filtering
    >>> results = await wrapper.search_videos(
    ...     query="machine learning",
    ...     platform="youtube", 
    ...     max_results=15
    ... )
    >>> # Filter by duration (videos longer than 30 minutes)
    >>> long_videos = [v for v in results['results'] if v['duration'] and v['duration'] > 1800]

Notes:
    - Search uses yt-dlp's built-in search functionality
    - Results include direct URLs suitable for download_video method
    - Description text is truncated to 200 characters for readability
    - URLs in results are ready for immediate downloading
    """
```
* **Async:** True
* **Method:** True
* **Class:** YtDlpWrapper
