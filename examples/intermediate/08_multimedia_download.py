"""
Multimedia Download and Processing

This example demonstrates how to download and process multimedia files using
yt-dlp (for video/audio from 1000+ sites) and FFmpeg (for media conversion).

Requirements:
    - yt-dlp: pip install yt-dlp
    - ffmpeg-python: pip install ffmpeg-python
    - ffmpeg system binary: apt install ffmpeg

Usage:
    python examples/08_multimedia_download.py
"""

import asyncio
from pathlib import Path


async def demo_ytdlp_info():
    """Get information about a video without downloading."""
    print("\n" + "="*70)
    print("DEMO 1: Video Information Extraction")
    print("="*70)
    
    try:
        from ipfs_datasets_py.processors.multimedia import YtDlpWrapper
        
        # Initialize wrapper
        print("\n📺 Initializing yt-dlp wrapper...")
        ytdlp = YtDlpWrapper()
        
        # Example URL (using a known stable video)
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"  # Never Gonna Give You Up
        
        print(f"\n🔍 Extracting information from: {url}")
        print("   (Not downloading, just getting metadata)")
        
        # Get info without downloading
        info = await ytdlp.extract_info(url, download=False)
        
        if info:
            print("\n✅ Video Information:")
            print(f"   Title: {info.get('title', 'N/A')}")
            print(f"   Uploader: {info.get('uploader', 'N/A')}")
            print(f"   Duration: {info.get('duration', 0)} seconds")
            print(f"   View count: {info.get('view_count', 0):,}")
            print(f"   Upload date: {info.get('upload_date', 'N/A')}")
            
            # Available formats
            formats = info.get('formats', [])
            print(f"\n   Available formats: {len(formats)}")
            if formats:
                # Show first few formats
                print("   Sample formats:")
                for fmt in formats[:3]:
                    print(f"      - {fmt.get('format_id')}: {fmt.get('ext')} "
                          f"{fmt.get('width', 'N/A')}x{fmt.get('height', 'N/A')}")
        
    except ImportError as e:
        print(f"\n❌ Missing dependencies: {e}")
        print("   Install with: pip install yt-dlp")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("   Note: Requires internet connection")


async def demo_ytdlp_download():
    """Download video/audio from supported sites."""
    print("\n" + "="*70)
    print("DEMO 2: Video/Audio Download")
    print("="*70)
    
    print("\n📥 Download Example (Demonstration Only)")
    print("   yt-dlp supports 1000+ websites including:")
    print("   - YouTube, Vimeo, Dailymotion")
    print("   - Twitter, Reddit, TikTok")
    print("   - Many news and educational sites")
    
    example_code = '''
from ipfs_datasets_py.processors.multimedia import YtDlpWrapper
import tempfile

ytdlp = YtDlpWrapper()

# Download audio only
audio_file = await ytdlp.download(
    url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    output_dir="/tmp/downloads",
    format="bestaudio",
    extract_audio=True
)

print(f"Downloaded audio: {audio_file}")

# Download video with specific quality
video_file = await ytdlp.download(
    url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    output_dir="/tmp/downloads",
    format="best[height<=720]",  # Max 720p
    extract_audio=False
)

print(f"Downloaded video: {video_file}")
    '''
    
    print(example_code)
    
    print("\n💡 Format Options:")
    print("   - 'bestaudio': Best audio quality")
    print("   - 'bestvideo': Best video quality")
    print("   - 'best': Best overall quality")
    print("   - 'best[height<=720]': Max 720p video")
    print("   - 'worstaudio/worst': Smallest file size")


async def demo_ffmpeg_conversion():
    """Convert media files using FFmpeg."""
    print("\n" + "="*70)
    print("DEMO 3: Media Conversion with FFmpeg")
    print("="*70)
    
    print("\n🎬 FFmpeg Conversion Example")
    print("   FFmpeg can convert between formats, extract audio, resize, etc.")
    
    example_code = '''
from ipfs_datasets_py.processors.multimedia import FFmpegWrapper

ffmpeg = FFmpegWrapper()

# Convert video format
await ffmpeg.convert(
    input_file="input.mp4",
    output_file="output.webm",
    codec="libvpx-vp9"  # VP9 codec for WebM
)

# Extract audio from video
await ffmpeg.extract_audio(
    input_file="video.mp4",
    output_file="audio.mp3",
    codec="libmp3lame"
)

# Resize video
await ffmpeg.resize(
    input_file="large_video.mp4",
    output_file="small_video.mp4",
    width=640,
    height=360
)

# Convert to GIF
await ffmpeg.to_gif(
    input_file="video.mp4",
    output_file="animation.gif",
    fps=10,
    scale=320
)
    '''
    
    print(example_code)


async def demo_media_info():
    """Get media file information."""
    print("\n" + "="*70)
    print("DEMO 4: Media Information Extraction")
    print("="*70)
    
    print("\n📊 Media Info Example")
    
    example_code = '''
from ipfs_datasets_py.processors.multimedia import MediaProcessor

processor = MediaProcessor()

# Get comprehensive media info
info = await processor.get_info("video.mp4")

print(f"Duration: {info['duration']} seconds")
print(f"Video codec: {info['video_codec']}")
print(f"Resolution: {info['width']}x{info['height']}")
print(f"Frame rate: {info['fps']} fps")
print(f"Audio codec: {info['audio_codec']}")
print(f"Bitrate: {info['bitrate']} kb/s")
print(f"File size: {info['size_mb']} MB")
    '''
    
    print(example_code)


async def demo_subtitle_extraction():
    """Extract subtitles from videos."""
    print("\n" + "="*70)
    print("DEMO 5: Subtitle Extraction")
    print("="*70)
    
    print("\n📝 Subtitle Extraction Example")
    
    example_code = '''
from ipfs_datasets_py.processors.multimedia import YtDlpWrapper

ytdlp = YtDlpWrapper()

# Download video with subtitles
await ytdlp.download(
    url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    output_dir="/tmp",
    write_subs=True,          # Download subtitles
    write_auto_subs=True,     # Download auto-generated subs
    sub_langs=["en", "es"],   # Languages to download
    sub_format="srt"          # Subtitle format
)

# Subtitles will be saved alongside the video
# video.mp4 -> video.en.srt, video.es.srt
    '''
    
    print(example_code)


async def demo_batch_download():
    """Batch download multiple videos."""
    print("\n" + "="*70)
    print("DEMO 6: Batch Download")
    print("="*70)
    
    print("\n📚 Batch Download Example")
    
    example_code = '''
from ipfs_datasets_py.processors.multimedia import YtDlpWrapper
import asyncio

ytdlp = YtDlpWrapper()

urls = [
    "https://www.youtube.com/watch?v=video1",
    "https://www.youtube.com/watch?v=video2",
    "https://www.youtube.com/watch?v=video3",
]

# Download all videos concurrently
tasks = [
    ytdlp.download(url, output_dir="/tmp/batch")
    for url in urls
]

results = await asyncio.gather(*tasks, return_exceptions=True)

# Check results
for url, result in zip(urls, results):
    if isinstance(result, Exception):
        print(f"Failed: {url} - {result}")
    else:
        print(f"Success: {url} -> {result}")
    '''
    
    print(example_code)


async def demo_playlist_download():
    """Download entire playlists."""
    print("\n" + "="*70)
    print("DEMO 7: Playlist Download")
    print("="*70)
    
    print("\n🎵 Playlist Download Example")
    
    example_code = '''
from ipfs_datasets_py.processors.multimedia import YtDlpWrapper

ytdlp = YtDlpWrapper()

# Download entire playlist
await ytdlp.download_playlist(
    url="https://www.youtube.com/playlist?list=PLxxxxxx",
    output_dir="/tmp/playlist",
    format="bestaudio",
    max_downloads=10  # Limit number of videos
)

# Or get playlist info first
playlist_info = await ytdlp.extract_info(
    "https://www.youtube.com/playlist?list=PLxxxxxx",
    download=False
)

print(f"Playlist: {playlist_info['title']}")
print(f"Videos: {len(playlist_info['entries'])}")
    '''
    
    print(example_code)


def show_tips():
    """Show tips for multimedia processing."""
    print("\n" + "="*70)
    print("TIPS FOR MULTIMEDIA PROCESSING")
    print("="*70)
    
    print("\n1. yt-dlp Best Practices:")
    print("   - Check site support: yt-dlp --list-extractors")
    print("   - Get info first before downloading")
    print("   - Use format selection for optimal quality/size")
    print("   - Respect rate limits and copyright")
    
    print("\n2. FFmpeg Optimization:")
    print("   - Hardware acceleration: Use -hwaccel cuda/vaapi")
    print("   - Preset selection: ultrafast to veryslow")
    print("   - CRF for quality: Lower = better (18-28 typical)")
    print("   - Two-pass encoding for best quality")
    
    print("\n3. Format Selection:")
    print("   - MP4: Best compatibility, good compression")
    print("   - WebM: Open format, good for web")
    print("   - MKV: Container for multiple streams")
    print("   - MP3/AAC: Good audio compression")
    
    print("\n4. Performance:")
    print("   - Download in parallel (with rate limiting)")
    print("   - Use FFmpeg filters for efficiency")
    print("   - Store intermediate files on fast storage")
    
    print("\n5. Common Tasks:")
    print("   - Extract audio: Use extract_audio()")
    print("   - Create thumbnails: FFmpeg frame extraction")
    print("   - Trim videos: FFmpeg -ss and -t options")
    print("   - Concatenate: FFmpeg concat demuxer")
    
    print("\n6. System Requirements:")
    print("   - yt-dlp: pip install yt-dlp")
    print("   - FFmpeg: apt install ffmpeg")
    print("   - Disk space: Consider file sizes")
    print("   - Network: Good bandwidth for downloads")
    
    print("\n7. Legal & Ethical:")
    print("   - Respect copyright and terms of service")
    print("   - Don't download copyrighted content")
    print("   - Use for personal/educational purposes")
    print("   - Follow platform rate limits")
    
    print("\n8. Next Steps:")
    print("   - See 09_batch_processing.py for scaling")
    print("   - Combine with embeddings for video understanding")


async def main():
    """Run all multimedia demonstrations."""
    print("\n" + "="*70)
    print("IPFS DATASETS PYTHON - MULTIMEDIA PROCESSING")
    print("="*70)
    
    print("\n⚠️  Note: Some demos require internet connection")
    print("   and may take time to download files.")
    
    await demo_ytdlp_info()
    await demo_ytdlp_download()
    await demo_ffmpeg_conversion()
    await demo_media_info()
    await demo_subtitle_extraction()
    await demo_batch_download()
    await demo_playlist_download()
    
    show_tips()
    
    print("\n" + "="*70)
    print("✅ MULTIMEDIA PROCESSING EXAMPLES COMPLETE")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
