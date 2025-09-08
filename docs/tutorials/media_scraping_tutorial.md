# Media Scraping and Processing Tutorial

This tutorial demonstrates how to scrape and process multimedia content from various platforms using IPFS Datasets Python's integrated FFmpeg and YT-DLP tools.

## Table of Contents

1. [Introduction](#introduction)
2. [Prerequisites](#prerequisites)
3. [Setting Up](#setting-up)
4. [Video and Audio Downloading with YT-DLP](#video-and-audio-downloading-with-yt-dlp)
5. [Media Processing with FFmpeg](#media-processing-with-ffmpeg)
6. [Batch Media Operations](#batch-media-operations)
7. [Creating Media Datasets](#creating-media-datasets)
8. [Advanced Media Processing](#advanced-media-processing)
9. [Complete Example](#complete-example)

## Introduction

IPFS Datasets Python provides comprehensive multimedia scraping and processing capabilities through integration with:

- **YT-DLP**: Download videos and audio from 1000+ platforms (YouTube, Vimeo, SoundCloud, TikTok, etc.)
- **FFmpeg**: Professional media processing, conversion, and analysis
- **Media Dataset Creation**: Convert scraped media into structured datasets for machine learning

## Prerequisites

- IPFS Datasets Python installed with media dependencies:
  ```bash
  pip install ipfs-datasets-py[media]
  pip install yt-dlp ffmpeg-python
  ```
- FFmpeg installed system-wide:
  ```bash
  # Ubuntu/Debian
  sudo apt install ffmpeg
  
  # macOS
  brew install ffmpeg
  
  # Windows
  choco install ffmpeg
  ```

## Setting Up

```python
from ipfs_datasets_py.multimedia import YtDlpWrapper, FFmpegWrapper
from ipfs_datasets_py.mcp_server.tools.media_tools import (
    ytdlp_download_video, ytdlp_download_playlist, ytdlp_extract_info,
    ffmpeg_convert, ffmpeg_probe, ffmpeg_batch_process
)
import os
import json
from pathlib import Path

# Create directories for media processing
media_dir = "scraped_media"
processed_dir = "processed_media"
dataset_dir = "media_datasets"

for directory in [media_dir, processed_dir, dataset_dir]:
    os.makedirs(directory, exist_ok=True)

print("Media scraping environment ready!")

# Initialize wrappers
ytdlp_wrapper = YtDlpWrapper(default_output_dir=media_dir)
ffmpeg_wrapper = FFmpegWrapper(default_output_dir=processed_dir)
```

## Video and Audio Downloading with YT-DLP

### Single Video Download

```python
# Download a single video with metadata
async def download_single_video():
    """Download a single video with full metadata."""
    result = await ytdlp_download_video(
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        output_dir=media_dir,
        quality="best[height<=720]",  # Limit to 720p
        download_info_json=True,
        download_thumbnails=True,
        subtitle_langs=["en", "auto"]
    )
    
    print(f"Download result: {result['status']}")
    if result['status'] == 'success':
        print(f"Downloaded file: {result['output_file']}")
        print(f"File size: {result['file_size']} bytes")
        print(f"Duration: {result['duration']} seconds")
    
    return result

# Run the download
import asyncio
video_result = asyncio.run(download_single_video())
```

### Playlist and Batch Downloads

```python
# Download entire playlist
async def download_playlist():
    """Download an entire playlist."""
    result = await ytdlp_download_playlist(
        url="https://www.youtube.com/playlist?list=PLrAXtmRdnEQy5JBZM-0P3KKiMxz5e3fXr",
        output_dir=f"{media_dir}/playlists",
        quality="best[height<=480]",  # Lower quality for batch
        max_downloads=5,  # Limit for demo
        download_info_json=True
    )
    
    print(f"Playlist download: {result['status']}")
    print(f"Downloaded {result['downloaded_count']} videos")
    
    return result

# Download from multiple platforms
async def multi_platform_download():
    """Download from various platforms."""
    urls = [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://vimeo.com/148751763",
        "https://soundcloud.com/user/track",
        "https://www.tiktok.com/@user/video/123456789"
    ]
    
    results = []
    for url in urls:
        try:
            result = await ytdlp_download_video(
                url=url,
                output_dir=f"{media_dir}/multi_platform",
                quality="best[height<=720]",
                audio_only=False,
                download_info_json=True
            )
            results.append(result)
            print(f"✅ Downloaded from {url.split('/')[2]}")
        except Exception as e:
            print(f"❌ Failed to download {url}: {e}")
            results.append({"status": "error", "url": url, "error": str(e)})
    
    return results

# Run batch downloads
playlist_result = asyncio.run(download_playlist())
multi_platform_results = asyncio.run(multi_platform_download())
```

### Audio-Only Downloads

```python
# Download audio-only content for podcast/music datasets
async def download_audio_content():
    """Download audio-only content from various sources."""
    
    # Download best quality audio from YouTube
    audio_result = await ytdlp_download_video(
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        output_dir=f"{media_dir}/audio",
        audio_only=True,
        audio_format="mp3",
        quality="bestaudio",
        download_info_json=True
    )
    
    # Extract audio from video
    video_to_audio = await ytdlp_download_video(
        url="https://www.youtube.com/watch?v=another_video",
        output_dir=f"{media_dir}/extracted_audio",
        extract_audio=True,
        audio_format="flac",  # High quality for analysis
        download_info_json=True
    )
    
    return [audio_result, video_to_audio]

# Download audio content
audio_results = asyncio.run(download_audio_content())
```

## Media Processing with FFmpeg

### Format Conversion and Quality Control

```python
# Convert downloaded videos to standardized format
async def standardize_media_formats():
    """Convert all downloaded media to standard formats."""
    
    # Find all downloaded video files
    video_files = list(Path(media_dir).rglob("*.mp4")) + list(Path(media_dir).rglob("*.webm"))
    
    conversion_results = []
    for video_file in video_files:
        output_path = processed_dir / f"{video_file.stem}_standardized.mp4"
        
        result = await ffmpeg_convert(
            input_file=str(video_file),
            output_file=str(output_path),
            video_codec="libx264",
            audio_codec="aac",
            resolution="1280x720",  # Standardize to 720p
            quality="medium",
            custom_options={
                "preset": "medium",
                "crf": "23"  # Good quality/size balance
            }
        )
        
        conversion_results.append(result)
        if result['status'] == 'success':
            print(f"✅ Converted: {video_file.name}")
        else:
            print(f"❌ Failed to convert: {video_file.name}")
    
    return conversion_results

# Run format standardization
conversion_results = asyncio.run(standardize_media_formats())
```

### Media Analysis and Metadata Extraction

```python
# Analyze media files for dataset creation
async def analyze_media_files():
    """Extract comprehensive metadata from media files."""
    
    media_files = list(Path(processed_dir).rglob("*.mp4"))
    analysis_results = []
    
    for media_file in media_files:
        # Get detailed media information
        probe_result = await ffmpeg_probe(
            input_file=str(media_file),
            show_format=True,
            show_streams=True,
            include_metadata=True
        )
        
        if probe_result['status'] == 'success':
            analysis_results.append({
                'file_path': str(media_file),
                'file_size': media_file.stat().st_size,
                'duration': probe_result.get('duration', 0),
                'format': probe_result.get('format_name', ''),
                'video_codec': probe_result.get('video_codec', ''),
                'audio_codec': probe_result.get('audio_codec', ''),
                'resolution': probe_result.get('resolution', ''),
                'bitrate': probe_result.get('bitrate', 0),
                'metadata': probe_result.get('metadata', {})
            })
            print(f"✅ Analyzed: {media_file.name}")
    
    return analysis_results

# Analyze all processed media
media_analysis = asyncio.run(analyze_media_files())

# Save analysis results
analysis_path = f"{dataset_dir}/media_analysis.json"
with open(analysis_path, 'w') as f:
    json.dump(media_analysis, f, indent=2)

print(f"Media analysis saved: {analysis_path}")
```

## Batch Media Operations

### Parallel Processing Pipeline

```python
# Process multiple files in parallel with different operations
async def batch_media_pipeline():
    """Run a complete batch processing pipeline."""
    
    # Find all raw downloaded files
    input_files = []
    for ext in ["*.mp4", "*.webm", "*.mkv", "*.avi"]:
        input_files.extend(list(Path(media_dir).rglob(ext)))
    
    # Batch convert to standard format
    conversion_result = await ffmpeg_batch_process(
        input_files=[str(f) for f in input_files],
        output_directory=processed_dir,
        operation="convert",
        operation_params={
            "video_codec": "libx264",
            "audio_codec": "aac",
            "resolution": "1280x720",
            "quality": "medium"
        },
        max_parallel=3,  # Process 3 files simultaneously
        timeout=1800  # 30 minutes per file
    )
    
    print(f"Batch conversion completed: {conversion_result['status']}")
    print(f"Processed {conversion_result['files_processed']} files")
    print(f"Success rate: {conversion_result['success_rate']:.1%}")
    
    return conversion_result

# Run batch processing
batch_result = asyncio.run(batch_media_pipeline())
```

### Content Extraction for Dataset Creation

```python
# Extract frames and audio for machine learning datasets
async def extract_content_for_ml():
    """Extract frames and audio segments for ML dataset creation."""
    
    processed_files = list(Path(processed_dir).rglob("*.mp4"))
    extractions = []
    
    for video_file in processed_files:
        try:
            # Extract frames at 1 FPS for image dataset
            frames_dir = dataset_dir / "frames" / video_file.stem
            frames_dir.mkdir(parents=True, exist_ok=True)
            
            frame_result = await ffmpeg_convert(
                input_file=str(video_file),
                output_file=str(frames_dir / "frame_%04d.jpg"),
                custom_options={
                    "vf": "fps=1",  # 1 frame per second
                    "q:v": "2"      # High quality JPEGs
                }
            )
            
            # Extract audio segments for audio processing
            audio_dir = dataset_dir / "audio" / video_file.stem  
            audio_dir.mkdir(parents=True, exist_ok=True)
            
            audio_result = await ffmpeg_convert(
                input_file=str(video_file),
                output_file=str(audio_dir / "audio.wav"),
                video_codec=None,  # Audio only
                audio_codec="pcm_s16le",  # Uncompressed for analysis
                audio_sampling_rate="44100"
            )
            
            extractions.append({
                'source_video': str(video_file),
                'frames_extracted': frame_result['status'] == 'success',
                'frames_directory': str(frames_dir),
                'audio_extracted': audio_result['status'] == 'success', 
                'audio_file': str(audio_dir / "audio.wav")
            })
            
            print(f"✅ Extracted content from: {video_file.name}")
            
        except Exception as e:
            print(f"❌ Failed to extract from {video_file.name}: {e}")
    
    return extractions

# Extract content for ML datasets
ml_extractions = asyncio.run(extract_content_for_ml())
```

## Creating Media Datasets

### Video Dataset Creation

```python
# Create a comprehensive video dataset
def create_video_dataset():
    """Create a structured video dataset from scraped content."""
    
    dataset_records = []
    
    # Combine download metadata with analysis results
    for analysis in media_analysis:
        # Find corresponding download metadata
        video_path = analysis['file_path']
        info_json_path = Path(video_path).with_suffix('.info.json')
        
        # Load YT-DLP metadata if available
        download_metadata = {}
        if info_json_path.exists():
            with open(info_json_path, 'r') as f:
                download_metadata = json.load(f)
        
        # Create dataset record
        record = {
            # File information
            'file_path': video_path,
            'file_size': analysis['file_size'],
            'format': analysis['format'],
            
            # Technical specifications  
            'duration': analysis['duration'],
            'resolution': analysis['resolution'],
            'video_codec': analysis['video_codec'],
            'audio_codec': analysis['audio_codec'],
            'bitrate': analysis['bitrate'],
            
            # Content metadata from YT-DLP
            'title': download_metadata.get('title', ''),
            'description': download_metadata.get('description', ''),
            'uploader': download_metadata.get('uploader', ''),
            'upload_date': download_metadata.get('upload_date', ''),
            'view_count': download_metadata.get('view_count', 0),
            'like_count': download_metadata.get('like_count', 0),
            'comment_count': download_metadata.get('comment_count', 0),
            'tags': download_metadata.get('tags', []),
            'categories': download_metadata.get('categories', []),
            
            # Platform information
            'platform': download_metadata.get('extractor', ''),
            'original_url': download_metadata.get('webpage_url', ''),
            'video_id': download_metadata.get('id', ''),
            
            # Processing information
            'processed_timestamp': time.time(),
            'extraction_method': 'ytdlp_ffmpeg_pipeline'
        }
        
        dataset_records.append(record)
    
    return dataset_records

# Create video dataset
video_dataset = create_video_dataset()

# Save video dataset
video_dataset_path = f"{dataset_dir}/video_dataset.json"
with open(video_dataset_path, 'w') as f:
    json.dump(video_dataset, f, indent=2)

print(f"Video dataset created: {video_dataset_path}")
print(f"Total videos: {len(video_dataset)}")

# Create summary statistics
import pandas as pd
df = pd.DataFrame(video_dataset)
print(f"Dataset summary:")
print(f"  - Total duration: {df['duration'].sum() / 3600:.1f} hours")
print(f"  - Average views: {df['view_count'].mean():,.0f}")
print(f"  - Platforms: {df['platform'].value_counts().to_dict()}")
print(f"  - Total file size: {df['file_size'].sum() / (1024**3):.1f} GB")
```

### Audio Dataset Creation

```python
# Create specialized audio dataset
def create_audio_dataset():
    """Create dataset focused on audio content."""
    
    # Find all audio files (both audio-only downloads and extracted audio)
    audio_files = []
    audio_files.extend(list(Path(media_dir).rglob("*.mp3")))
    audio_files.extend(list(Path(media_dir).rglob("*.flac")))
    audio_files.extend(list(Path(dataset_dir).rglob("*.wav")))  # Extracted audio
    
    audio_records = []
    
    for audio_file in audio_files:
        # Get audio file analysis
        try:
            probe_result = asyncio.run(ffmpeg_probe(
                input_file=str(audio_file),
                show_format=True,
                show_streams=True
            ))
            
            if probe_result['status'] == 'success':
                # Look for corresponding metadata
                info_json = audio_file.with_suffix('.info.json')
                metadata = {}
                if info_json.exists():
                    with open(info_json, 'r') as f:
                        metadata = json.load(f)
                
                record = {
                    'file_path': str(audio_file),
                    'file_size': audio_file.stat().st_size,
                    'duration': probe_result.get('duration', 0),
                    'audio_codec': probe_result.get('audio_codec', ''),
                    'sample_rate': probe_result.get('sample_rate', 0),
                    'channels': probe_result.get('channels', 0),
                    'bitrate': probe_result.get('bitrate', 0),
                    
                    # Content metadata
                    'title': metadata.get('title', ''),
                    'artist': metadata.get('uploader', ''),
                    'description': metadata.get('description', ''),
                    'genre': metadata.get('genre', ''),
                    'platform': metadata.get('extractor', ''),
                    'original_url': metadata.get('webpage_url', ''),
                    
                    # Classification
                    'content_type': 'music' if 'music' in str(audio_file).lower() else 'speech',
                    'source_type': 'direct_download' if 'multi_platform' in str(audio_file) else 'extracted'
                }
                
                audio_records.append(record)
                print(f"✅ Processed audio: {audio_file.name}")
                
        except Exception as e:
            print(f"❌ Failed to analyze {audio_file.name}: {e}")
    
    return audio_records

# Create audio dataset
audio_dataset = create_audio_dataset()

# Save audio dataset
audio_dataset_path = f"{dataset_dir}/audio_dataset.json"
with open(audio_dataset_path, 'w') as f:
    json.dump(audio_dataset, f, indent=2)

print(f"Audio dataset created: {audio_dataset_path}")
print(f"Total audio files: {len(audio_dataset)}")
```

## Advanced Media Processing

### Content Analysis and Feature Extraction

```python
# Advanced audio analysis for content classification
def analyze_audio_features(audio_dataset):
    """Analyze audio features for content classification."""
    
    try:
        import librosa
        import numpy as np
        
        enhanced_records = []
        
        for record in audio_dataset:
            audio_path = record['file_path']
            
            try:
                # Load audio with librosa
                y, sr = librosa.load(audio_path, duration=30)  # First 30 seconds
                
                # Extract audio features
                features = {
                    'tempo': float(librosa.beat.tempo(y=y, sr=sr)[0]),
                    'spectral_centroid': float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr))),
                    'spectral_rolloff': float(np.mean(librosa.feature.spectral_rolloff(y=y, sr=sr))),
                    'zero_crossing_rate': float(np.mean(librosa.feature.zero_crossing_rate(y))),
                    'mfcc_mean': np.mean(librosa.feature.mfcc(y=y, sr=sr), axis=1).tolist()[:13]
                }
                
                # Add features to record
                enhanced_record = record.copy()
                enhanced_record['audio_features'] = features
                enhanced_record['analysis_status'] = 'success'
                
                enhanced_records.append(enhanced_record)
                print(f"✅ Analyzed features: {Path(audio_path).name}")
                
            except Exception as e:
                record['analysis_status'] = 'error'
                record['analysis_error'] = str(e)
                enhanced_records.append(record)
                print(f"❌ Failed to analyze: {Path(audio_path).name}")
        
        return enhanced_records
        
    except ImportError:
        print("librosa not available. Install with: pip install librosa")
        return audio_dataset

# Enhance audio dataset with features
enhanced_audio_dataset = analyze_audio_features(audio_dataset)
```

### Video Frame Analysis

```python
# Analyze video frames for computer vision datasets
def analyze_video_frames():
    """Analyze extracted video frames for CV datasets."""
    
    frames_dirs = list(Path(dataset_dir / "frames").glob("*"))
    frame_analysis = []
    
    for frames_dir in frames_dirs:
        frame_files = list(frames_dir.glob("*.jpg"))
        
        if frame_files:
            # Basic frame analysis
            frame_info = {
                'video_source': frames_dir.name,
                'frame_count': len(frame_files),
                'frames_directory': str(frames_dir),
                'average_file_size': sum(f.stat().st_size for f in frame_files) / len(frame_files),
                'frame_paths': [str(f) for f in frame_files]
            }
            
            # Optional: Add computer vision analysis
            try:
                from PIL import Image
                import numpy as np
                
                # Sample frame analysis
                sample_frame = Image.open(frame_files[0])
                frame_info.update({
                    'frame_width': sample_frame.width,
                    'frame_height': sample_frame.height,
                    'frame_mode': sample_frame.mode,
                    'estimated_fps': 1  # We extracted at 1 FPS
                })
                
            except ImportError:
                print("PIL not available for frame analysis")
            
            frame_analysis.append(frame_info)
            print(f"✅ Analyzed frames from: {frames_dir.name}")
    
    return frame_analysis

# Analyze video frames
frame_analysis = analyze_video_frames()

# Save frame analysis
frame_analysis_path = f"{dataset_dir}/frame_analysis.json"
with open(frame_analysis_path, 'w') as f:
    json.dump(frame_analysis, f, indent=2)
```

## Complete Example

Here's a complete end-to-end example combining all techniques:

```python
#!/usr/bin/env python3
"""
Complete Media Scraping and Processing Pipeline

This example demonstrates downloading content from multiple platforms,
processing it with FFmpeg, and creating structured ML-ready datasets.
"""

import asyncio
import json
import time
import os
from pathlib import Path
from ipfs_datasets_py.multimedia import YtDlpWrapper, FFmpegWrapper
from ipfs_datasets_py.mcp_server.tools.media_tools import *

async def complete_media_pipeline():
    """Complete media scraping and processing pipeline."""
    
    print("🎬 Starting complete media pipeline...")
    
    # Setup directories
    base_dir = "complete_media_pipeline"
    raw_dir = f"{base_dir}/raw"
    processed_dir = f"{base_dir}/processed"
    dataset_dir = f"{base_dir}/datasets"
    
    for directory in [raw_dir, processed_dir, dataset_dir]:
        os.makedirs(directory, exist_ok=True)
    
    # 1. Scrape content from multiple platforms
    print("\\n📥 Downloading content from multiple platforms...")
    
    content_urls = [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://vimeo.com/148751763", 
        # Add more URLs as needed
    ]
    
    download_results = []
    for url in content_urls:
        try:
            result = await ytdlp_download_video(
                url=url,
                output_dir=raw_dir,
                quality="best[height<=720]",
                download_info_json=True,
                download_thumbnails=True,
                subtitle_langs=["en"]
            )
            download_results.append(result)
            print(f"✅ Downloaded: {url}")
        except Exception as e:
            print(f"❌ Failed: {url} - {e}")
            download_results.append({"status": "error", "url": url, "error": str(e)})
    
    # 2. Process all downloaded content
    print("\\n🔄 Processing downloaded content...")
    
    # Find all downloaded files
    video_files = list(Path(raw_dir).rglob("*.mp4"))
    video_files.extend(list(Path(raw_dir).rglob("*.webm")))
    
    # Batch process to standard format
    if video_files:
        batch_result = await ffmpeg_batch_process(
            input_files=[str(f) for f in video_files],
            output_directory=processed_dir,
            operation="convert",
            operation_params={
                "video_codec": "libx264",
                "audio_codec": "aac", 
                "resolution": "854x480",  # Standard definition
                "quality": "medium"
            },
            max_parallel=2
        )
        print(f"Batch processing: {batch_result['status']}")
    
    # 3. Extract content for ML datasets
    print("\\n🎯 Extracting content for ML datasets...")
    
    processed_files = list(Path(processed_dir).rglob("*.mp4"))
    ml_extractions = []
    
    for video_file in processed_files:
        # Extract audio for speech/music analysis
        audio_output = dataset_dir / "audio" / f"{video_file.stem}.wav"
        audio_output.parent.mkdir(parents=True, exist_ok=True)
        
        audio_result = await ffmpeg_convert(
            input_file=str(video_file),
            output_file=str(audio_output),
            video_codec=None,
            audio_codec="pcm_s16le",
            audio_sampling_rate="16000"  # Standard for speech processing
        )
        
        # Extract frames for computer vision
        frames_dir = dataset_dir / "frames" / video_file.stem
        frames_dir.mkdir(parents=True, exist_ok=True)
        
        frames_result = await ffmpeg_convert(
            input_file=str(video_file),
            output_file=str(frames_dir / "frame_%04d.jpg"),
            custom_options={"vf": "fps=0.5"}  # One frame every 2 seconds
        )
        
        ml_extractions.append({
            'source_video': str(video_file),
            'audio_extracted': audio_result['status'] == 'success',
            'audio_path': str(audio_output),
            'frames_extracted': frames_result['status'] == 'success',
            'frames_directory': str(frames_dir)
        })
    
    # 4. Create final structured dataset
    print("\\n📊 Creating structured dataset...")
    
    final_dataset = {
        'metadata': {
            'created_at': time.time(),
            'total_videos': len(download_results),
            'successful_downloads': len([r for r in download_results if r.get('status') == 'success']),
            'processing_pipeline': 'ytdlp_ffmpeg_ipfs_datasets',
            'formats_included': ['video', 'audio', 'frames', 'metadata']
        },
        'videos': video_dataset,
        'audio_extractions': ml_extractions,
        'download_logs': download_results,
        'frame_analysis': frame_analysis
    }
    
    # Save comprehensive dataset
    final_dataset_path = f"{dataset_dir}/complete_media_dataset.json"
    with open(final_dataset_path, 'w') as f:
        json.dump(final_dataset, f, indent=2)
    
    # Create CSV for analysis
    videos_df = pd.DataFrame(video_dataset)
    videos_df.to_csv(f"{dataset_dir}/videos_analysis.csv", index=False)
    
    print(f"\\n🎉 Complete media dataset created!")
    print(f"  - Dataset file: {final_dataset_path}")
    print(f"  - Videos CSV: {dataset_dir}/videos_analysis.csv")
    print(f"  - Total videos processed: {len(video_dataset)}")
    
    return final_dataset

# Run complete pipeline
if __name__ == "__main__":
    complete_dataset = asyncio.run(complete_media_pipeline())
    print("\\n✨ Media scraping and processing pipeline completed!")
```

This tutorial demonstrated how to scrape multimedia content from various platforms, process it with professional tools, and create structured datasets ready for machine learning and analysis workflows.