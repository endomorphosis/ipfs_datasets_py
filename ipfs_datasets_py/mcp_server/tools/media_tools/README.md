# Media Tools

MCP tools for audio/video processing using FFmpeg, and downloading media from 1000+ platforms
using yt-dlp. All tools are thin wrappers around `ipfs_datasets_py.data_transformation.multimedia`.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `ffmpeg_info.py` | `ffmpeg_info()`, `ffprobe_streams()` | Probe media file metadata, codec info, duration, stream details |
| `ffmpeg_convert.py` | `ffmpeg_convert()` | Convert video/audio between formats (MP4, MKV, WebM, MP3, AAC, etc.) |
| `ffmpeg_edit.py` | `ffmpeg_trim()`, `ffmpeg_concat()`, `ffmpeg_splice()` | Cut, join, and splice media files |
| `ffmpeg_filters.py` | `ffmpeg_apply_filter()`, `ffmpeg_chain_filters()` | Apply video/audio filters (resize, denoise, normalize, etc.) |
| `ffmpeg_mux_demux.py` | `ffmpeg_mux()`, `ffmpeg_demux()`, `ffmpeg_extract_audio()` | Mux/demux streams, extract audio tracks |
| `ffmpeg_stream.py` | `ffmpeg_stream_info()`, `ffmpeg_hls_segment()` | HLS segmentation, live stream operations |
| `ffmpeg_batch.py` | `ffmpeg_batch_convert()`, `ffmpeg_batch_process()` | Batch convert/process multiple media files |
| `ffmpeg_utils.py` | `ffmpeg_thumbnail()`, `ffmpeg_gif()` | Utility operations (thumbnail extraction, GIF creation) |
| `ytdlp_download.py` | `ytdlp_download()`, `ytdlp_playlist()`, `ytdlp_info()` | Download from YouTube, Vimeo, Twitch, and 1000+ other platforms |

## Usage

### Get media file info

```python
from ipfs_datasets_py.mcp_server.tools.media_tools import ffmpeg_info

info = await ffmpeg_info(
    input_path="/data/video.mp4"
)
# Returns: {"status": "success", "format": "mp4", "duration": 120.5, "streams": [...]}
```

### Convert video format

```python
from ipfs_datasets_py.mcp_server.tools.media_tools import ffmpeg_convert

result = await ffmpeg_convert(
    input_path="/data/video.mp4",
    output_path="/data/video.webm",
    video_codec="libvpx-vp9",
    audio_codec="libopus",
    video_bitrate="2M"
)
```

### Trim a video clip

```python
from ipfs_datasets_py.mcp_server.tools.media_tools import ffmpeg_trim

result = await ffmpeg_trim(
    input_path="/data/video.mp4",
    output_path="/data/clip.mp4",
    start_time="00:01:30",     # HH:MM:SS or seconds
    end_time="00:02:45"
)
```

### Extract audio track

```python
from ipfs_datasets_py.mcp_server.tools.media_tools import ffmpeg_extract_audio

result = await ffmpeg_extract_audio(
    input_path="/data/video.mp4",
    output_path="/data/audio.mp3",
    audio_codec="libmp3lame",
    audio_bitrate="192k"
)
```

### Download from YouTube/platform

```python
from ipfs_datasets_py.mcp_server.tools.media_tools import ytdlp_download

result = await ytdlp_download(
    url="https://www.youtube.com/watch?v=...",
    output_path="/data/downloads/",
    format="bestvideo+bestaudio",    # yt-dlp format selector
    audio_only=False,
    extract_info=True                # Also return video metadata
)
```

### Download a playlist

```python
from ipfs_datasets_py.mcp_server.tools.media_tools import ytdlp_playlist

result = await ytdlp_playlist(
    url="https://www.youtube.com/playlist?list=...",
    output_path="/data/playlist/",
    max_downloads=20,
    audio_only=True
)
```

### Batch convert

```python
from ipfs_datasets_py.mcp_server.tools.media_tools import ffmpeg_batch_convert

result = await ffmpeg_batch_convert(
    input_dir="/data/raw/",
    output_dir="/data/processed/",
    input_pattern="*.avi",
    output_format="mp4",
    parallel_jobs=4
)
```

## Core Module

All business logic delegates to:
- `ipfs_datasets_py.data_transformation.multimedia.ffmpeg_wrapper` — FFmpeg operations
- `ipfs_datasets_py.data_transformation.multimedia.ytdlp_wrapper` — yt-dlp operations

## Dependencies

**Required (tools return an error if missing):**
- `ffmpeg` — must be installed as a system binary (or via `pip install ffmpeg-python`)
- `yt-dlp` — must be installed (`pip install yt-dlp`)

**Optional:**
- `ffmpeg-python` — Python bindings for FFmpeg (fallback to subprocess)

## Supported Platforms for yt-dlp

yt-dlp supports 1000+ platforms including YouTube, Vimeo, Twitch, SoundCloud, Dailymotion,
TikTok, Bilibili, and many more. See https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md

## Status

| Tool | Status |
|------|--------|
| `ffmpeg_info` | ✅ Production ready |
| `ffmpeg_convert` | ✅ Production ready |
| `ffmpeg_edit` | ✅ Production ready |
| `ffmpeg_filters` | ✅ Production ready |
| `ffmpeg_mux_demux` | ✅ Production ready |
| `ytdlp_download` | ✅ Production ready |
| `ffmpeg_batch` | ✅ Production ready |
| `ffmpeg_stream` | ⚠️ Live streaming requires additional setup |
