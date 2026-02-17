# Comprehensive Web Scraping and Archiving Guide

This guide provides comprehensive documentation for all web scraping and archiving capabilities in IPFS Datasets Python, covering traditional web archiving, multimedia content scraping, and integration with major archive services.

## Overview

IPFS Datasets Python provides enterprise-grade web scraping and archiving through multiple integrated services:

### 🌐 **Web Archive Services**
- **InterPlanetary Wayback Machine (IPWB)** - Decentralized web archiving on IPFS
- **Internet Archive Wayback Machine** - Historical web content access
- **Archive.is (archive.today)** - Permanent webpage snapshots
- **Perma.cc** - Academic and legal webpage preservation
- **Common Crawl** - Large-scale web crawl data access

### 🎬 **Multimedia Platforms**
- **YT-DLP Integration** - Download from 1000+ platforms (YouTube, Vimeo, TikTok, SoundCloud, etc.)
- **FFmpeg Processing** - Professional media conversion and analysis
- **Batch Operations** - Parallel processing for large datasets

### 📊 **Dataset Creation**
- **Structured Data Extraction** - Convert web content to ML-ready datasets
- **Multi-format Output** - Parquet, Arrow, JSON, CSV support
- **IPFS Storage** - Decentralized dataset distribution
- **Content Analysis** - Language detection, deduplication, link analysis

## Quick Start

### Basic Web Archiving

```python
from ipfs_datasets_py.processors.web_archiving.web_archive_utils import WebArchiveProcessor
from archivenow import archivenow

# Initialize processor
processor = WebArchiveProcessor()

# Archive a website locally
warc_file = processor.create_warc(
    url="https://example.com",
    output_path="archives/example.warc.gz",
    options={"agent": "wget", "depth": 2}
)

# Archive to multiple services simultaneously
ia_url = archivenow.push("https://example.com", "ia")        # Internet Archive
is_url = archivenow.push("https://example.com", "is")        # Archive.is
cc_url = archivenow.push("https://example.com", "cc")        # Perma.cc

print(f"Archived to:")
print(f"  - Local WARC: {warc_file}")
print(f"  - Internet Archive: {ia_url}")
print(f"  - Archive.is: {is_url}")
print(f"  - Perma.cc: {cc_url}")
```

### Basic Media Scraping

```python
from ipfs_datasets_py.mcp_server.tools.media_tools import ytdlp_download_video
import asyncio

# Download video with metadata
result = await ytdlp_download_video(
    url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    output_dir="media_downloads",
    quality="best[height<=720]",
    download_info_json=True,
    subtitle_langs=["en"]
)

print(f"Downloaded: {result['output_file']}")
print(f"Duration: {result['duration']} seconds")
```

## Web Archive Services Integration

### 1. InterPlanetary Wayback Machine (IPWB)

Decentralized web archiving using IPFS for distributed storage and access.

#### Features
- **IPFS Storage**: Archives stored on distributed network
- **Content Deduplication**: Automatic dedup through content-addressing  
- **Memento Protocol**: Standard temporal web access
- **Encryption Support**: End-to-end encrypted archives
- **Distributed Replay**: Access archives from any IPFS node

#### Usage

```python
# Create and index archive to IPFS
warc_path = processor.create_warc(
    url="https://example.com",
    options={"agent": "squidwarc", "depth": 3}  # For dynamic sites
)

# Index to IPFS with IPWB
index_result = processor.index_warc(
    warc_path=warc_path,
    output_path="indexes/example.cdxj",
    encryption_key="your-encryption-key"  # Optional encryption
)

print(f"IPFS hash: {index_result['ipfs_hash']}")
print(f"Access via: http://localhost:5000/memento/*/http://example.com/")

# Extract structured data
dataset = processor.extract_dataset_from_cdxj(
    index_result['cdxj_path'],
    output_format="arrow"
)
```

### 2. Internet Archive Wayback Machine

Access historical web content from the Internet Archive.

#### Features
- **Historical Content**: Access websites as they appeared in the past
- **CDX API**: Programmatic query interface
- **Bulk Downloads**: Download multiple captures efficiently
- **Metadata Access**: Rich temporal and technical metadata

#### Usage

```python
import requests
import json

def query_wayback_machine(url, from_date="20200101", to_date="20240101"):
    """Query Wayback Machine for historical captures."""
    cdx_url = "http://web.archive.org/cdx/search/cdx"
    params = {
        'url': url,
        'from': from_date,
        'to': to_date,
        'output': 'json',
        'limit': 1000,
        'filter': 'statuscode:200'  # Only successful captures
    }
    
    response = requests.get(cdx_url, params=params)
    captures = response.json()[1:]  # Skip header row
    
    return captures

# Query historical captures
captures = query_wayback_machine("example.com")
print(f"Found {len(captures)} historical captures")

# Download specific captures
def download_wayback_capture(timestamp, url):
    """Download specific Wayback Machine capture."""
    wayback_url = f"http://web.archive.org/web/{timestamp}id_/{url}"
    response = requests.get(wayback_url)
    return response.content

# Process historical data for temporal analysis
temporal_dataset = []
for capture in captures[:10]:  # Process first 10 captures
    timestamp, original_url = capture[0], capture[1]
    content = download_wayback_capture(timestamp, original_url)
    
    temporal_dataset.append({
        'url': original_url,
        'capture_timestamp': timestamp,
        'content': content.decode('utf-8', errors='ignore'),
        'wayback_url': f"http://web.archive.org/web/{timestamp}/{original_url}"
    })
```

### 3. Archive.is (archive.today) Integration

Permanent webpage snapshots with immediate availability.

#### Features
- **Permanent Snapshots**: Immutable webpage preservation
- **Immediate Access**: Available immediately after archiving
- **Full Page Capture**: Complete webpage rendering including CSS/JS
- **API Access**: Programmatic archiving interface

#### Usage

```python
import requests
import time

def archive_to_archive_is(url):
    """Archive URL to archive.is service."""
    response = requests.post(
        'https://archive.is/submit/',
        data={'url': url},
        headers={
            'User-Agent': 'IPFS Datasets Archive Bot 1.0',
            'Accept': 'text/html,application/xhtml+xml'
        },
        timeout=60,
        allow_redirects=True
    )
    
    if response.status_code == 200:
        archive_url = response.url
        print(f"Archived to archive.is: {url} -> {archive_url}")
        return archive_url
    else:
        raise Exception(f"Archive.is failed with status: {response.status_code}")

# Archive multiple URLs with rate limiting
urls_to_archive = [
    "https://example.com",
    "https://blog.example.com", 
    "https://docs.example.com"
]

archive_is_results = []
for url in urls_to_archive:
    try:
        archive_url = archive_to_archive_is(url)
        archive_is_results.append({
            'original_url': url,
            'archive_url': archive_url,
            'archived_at': time.time()
        })
        time.sleep(3)  # Rate limiting
    except Exception as e:
        print(f"Failed to archive {url}: {e}")

# Verify archived content
def verify_archive_is_content(archive_url):
    """Verify and extract metadata from archive.is snapshot."""
    response = requests.get(archive_url, timeout=30)
    if response.status_code == 200:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.content, 'html.parser')
        
        return {
            'archive_url': archive_url,
            'content_length': len(response.content),
            'title': soup.title.string if soup.title else '',
            'archived_content': soup.get_text()[:1000]  # First 1000 chars
        }
    return None
```

### 4. Common Crawl Integration

Access massive web crawl datasets for large-scale content analysis.

#### Features
- **Massive Scale**: Billions of webpages from monthly crawls
- **Index API**: Query crawl data by URL patterns
- **WARC Downloads**: Download full content including headers
- **Metadata Rich**: Comprehensive page metadata and statistics

#### Usage

```python
def query_common_crawl_comprehensive(domain, crawl_ids=None, filters=None):
    """Comprehensive Common Crawl querying with advanced filtering."""
    if crawl_ids is None:
        crawl_ids = ["CC-MAIN-2024-10", "CC-MAIN-2024-06"]  # Recent crawls
    
    all_results = []
    
    for crawl_id in crawl_ids:
        cc_url = f"https://index.commoncrawl.org/{crawl_id}-index"
        params = {
            'url': f"*.{domain}/*",
            'output': 'json',
            'limit': 1000
        }
        
        response = requests.get(cc_url, params=params, timeout=60)
        crawl_results = []
        
        for line in response.text.strip().split('\\n'):
            if line:
                try:
                    record = json.loads(line)
                    
                    # Apply filters if provided
                    if filters:
                        if 'mime_types' in filters:
                            if record.get('mime', '') not in filters['mime_types']:
                                continue
                        if 'min_length' in filters:
                            if int(record.get('length', 0)) < filters['min_length']:
                                continue
                        if 'status_codes' in filters:
                            if record.get('status', '') not in filters['status_codes']:
                                continue
                    
                    record['crawl_id'] = crawl_id
                    crawl_results.append(record)
                    
                except json.JSONDecodeError:
                    continue
        
        all_results.extend(crawl_results)
        print(f"Found {len(crawl_results)} records in {crawl_id}")
    
    return all_results

# Query with comprehensive filters
cc_results = query_common_crawl_comprehensive(
    domain="stackoverflow.com",
    crawl_ids=["CC-MAIN-2024-10", "CC-MAIN-2024-06"],
    filters={
        'mime_types': ['text/html'],
        'status_codes': ['200'],
        'min_length': 1000
    }
)

# Download and process Common Crawl WARC records
def download_cc_warc_records(records, max_records=10):
    """Download actual content from Common Crawl WARC files."""
    downloaded_content = []
    
    for record in records[:max_records]:
        warc_url = record['url']
        offset = int(record['offset'])
        length = int(record['length'])
        
        # Download specific byte range from WARC
        headers = {'Range': f'bytes={offset}-{offset + length - 1}'}
        response = requests.get(warc_url, headers=headers, timeout=30)
        
        if response.status_code == 206:  # Partial content
            downloaded_content.append({
                'original_url': record['url'],
                'warc_content': response.content,
                'crawl_id': record['crawl_id'],
                'timestamp': record['timestamp'],
                'mime_type': record.get('mime', ''),
                'content_length': length
            })
            print(f"✅ Downloaded CC record: {record['url']}")
        else:
            print(f"❌ Failed to download: {record['url']}")
    
    return downloaded_content

# Download sample Common Crawl content
cc_content = download_cc_warc_records(cc_results, max_records=5)
```

## Multimedia Content Scraping

### YT-DLP Platform Support

Download content from 1000+ platforms with comprehensive metadata extraction.

#### Supported Platforms
- **Video**: YouTube, Vimeo, Dailymotion, TikTok, Instagram, Twitter
- **Audio**: SoundCloud, Bandcamp, Spotify (metadata), Apple Podcasts
- **Live Streams**: Twitch, YouTube Live, Facebook Live
- **Educational**: Coursera, edX, Khan Academy
- **News**: BBC iPlayer, CNN, NBC

#### Advanced Download Strategies

```python
# Platform-specific optimization strategies
platform_strategies = {
    'youtube': {
        'quality': 'best[height<=1080][ext=mp4]',
        'writesubtitles': True,
        'writeautomaticsub': True,
        'writecomments': True,
        'getcomments': True
    },
    'tiktok': {
        'quality': 'best[height<=720]',
        'writeinfojson': True,
        'writethumbnail': True
    },
    'soundcloud': {
        'format': 'bestaudio[ext=mp3]',
        'writeinfojson': True,
        'writethumbnail': True
    }
}

async def smart_platform_download(url, output_dir):
    """Download with automatic platform detection and optimization."""
    
    # Extract platform from URL
    if 'youtube.com' in url or 'youtu.be' in url:
        platform = 'youtube'
    elif 'tiktok.com' in url:
        platform = 'tiktok'
    elif 'soundcloud.com' in url:
        platform = 'soundcloud'
    else:
        platform = 'generic'
    
    # Use platform-specific options
    custom_opts = platform_strategies.get(platform, {})
    
    return await ytdlp_download_video(
        url=url,
        output_dir=f"{output_dir}/{platform}",
        custom_opts=custom_opts
    )

# Batch download from multiple platforms
urls = [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://vimeo.com/148751763",
    "https://soundcloud.com/user/track",
    "https://www.tiktok.com/@user/video/123456789"
]

results = []
for url in urls:
    result = await smart_platform_download(url, "multi_platform_downloads")
    results.append(result)
```

### Content-Aware Processing

```python
# Analyze downloaded content for intelligent processing
async def analyze_and_process_content(download_results):
    """Analyze content and apply appropriate processing."""
    
    processing_results = []
    
    for result in download_results:
        if result['status'] != 'success':
            continue
            
        file_path = result['output_file']
        content_type = result.get('content_type', 'unknown')
        
        # Analyze media file
        analysis = await ffmpeg_probe(
            input_file=file_path,
            show_format=True,
            show_streams=True
        )
        
        # Apply content-specific processing
        if 'audio' in content_type or analysis.get('has_video') == False:
            # Audio-only content - extract high quality audio
            processed_result = await ffmpeg_convert(
                input_file=file_path,
                output_file=f"processed/audio/{Path(file_path).stem}.wav",
                video_codec=None,
                audio_codec="pcm_s16le",
                audio_sampling_rate="44100"
            )
        
        elif analysis.get('duration', 0) > 3600:  # Long videos (>1 hour)
            # Long content - create segments and extract keyframes
            segments_result = await ffmpeg_cut(
                input_file=file_path,
                output_file=f"processed/segments/{Path(file_path).stem}_segment_%03d.mp4",
                segment_duration="00:10:00"  # 10-minute segments
            )
            
            # Extract keyframes for thumbnails
            keyframes_result = await ffmpeg_convert(
                input_file=file_path,
                output_file=f"processed/keyframes/{Path(file_path).stem}_keyframe_%04d.jpg",
                custom_options={"vf": "select='eq(pict_type,I)'", "vsync": "vfr"}
            )
            
        else:
            # Standard video - standardize format
            processed_result = await ffmpeg_convert(
                input_file=file_path,
                output_file=f"processed/standard/{Path(file_path).stem}_standard.mp4",
                video_codec="libx264",
                audio_codec="aac",
                resolution="1280x720",
                quality="medium"
            )
        
        processing_results.append({
            'original_file': file_path,
            'content_type': content_type,
            'processing_applied': 'audio_extraction' if 'audio' in content_type else 'standardization',
            'analysis': analysis
        })
    
    return processing_results
```

## Advanced Integration Patterns

### 1. Multi-Source Dataset Creation

```python
async def create_multi_source_dataset(config):
    """Create dataset from multiple web scraping sources."""
    
    dataset_records = []
    
    # Web archive sources
    for web_source in config.get('web_sources', []):
        # Create local archive
        warc_path = processor.create_warc(
            url=web_source['url'],
            options=web_source.get('options', {})
        )
        
        # Extract content
        text_data = processor.extract_text_from_warc(warc_path)
        
        for record in text_data:
            dataset_record = {
                'source_type': 'web_archive',
                'url': record['url'],
                'title': record.get('title', ''),
                'content': record.get('text', ''),
                'content_type': 'text/html',
                'extraction_method': 'warc_processing',
                'timestamp': record.get('timestamp'),
                'warc_file': warc_path
            }
            dataset_records.append(dataset_record)
    
    # Multimedia sources
    for media_source in config.get('media_sources', []):
        download_result = await ytdlp_download_video(
            url=media_source['url'],
            output_dir="multimedia_content",
            download_info_json=True
        )
        
        if download_result['status'] == 'success':
            # Load metadata
            info_json_path = Path(download_result['output_file']).with_suffix('.info.json')
            metadata = {}
            if info_json_path.exists():
                with open(info_json_path, 'r') as f:
                    metadata = json.load(f)
            
            dataset_record = {
                'source_type': 'multimedia',
                'url': media_source['url'],
                'title': metadata.get('title', ''),
                'content': metadata.get('description', ''),
                'content_type': 'video/audio',
                'file_path': download_result['output_file'],
                'platform': metadata.get('extractor', ''),
                'duration': metadata.get('duration', 0),
                'view_count': metadata.get('view_count', 0),
                'upload_date': metadata.get('upload_date'),
                'extraction_method': 'ytdlp_download'
            }
            dataset_records.append(dataset_record)
    
    # Historical archive sources (Wayback Machine)
    for historical_source in config.get('historical_sources', []):
        captures = query_wayback_machine(
            historical_source['url'],
            from_date=historical_source.get('from_date'),
            to_date=historical_source.get('to_date')
        )
        
        for capture in captures[:historical_source.get('max_captures', 10)]:
            timestamp, original_url = capture[0], capture[1]
            wayback_url = f"http://web.archive.org/web/{timestamp}/{original_url}"
            
            dataset_record = {
                'source_type': 'wayback_machine',
                'url': original_url,
                'wayback_url': wayback_url,
                'content_type': 'archived_webpage',
                'timestamp': timestamp,
                'archive_date': f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]}",
                'extraction_method': 'wayback_api'
            }
            dataset_records.append(dataset_record)
    
    return dataset_records

# Example configuration for multi-source dataset
dataset_config = {
    'web_sources': [
        {'url': 'https://example.com', 'options': {'agent': 'wget', 'depth': 1}},
        {'url': 'https://blog.example.com', 'options': {'agent': 'squidwarc', 'depth': 1}}
    ],
    'media_sources': [
        {'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'},
        {'url': 'https://soundcloud.com/user/track'}
    ],
    'historical_sources': [
        {'url': 'example.com', 'from_date': '20200101', 'to_date': '20240101', 'max_captures': 5}
    ]
}

# Create comprehensive dataset
multi_source_dataset = await create_multi_source_dataset(dataset_config)

# Save in multiple formats
import pandas as pd

# JSON format for programmatic access
with open('comprehensive_dataset.json', 'w') as f:
    json.dump(multi_source_dataset, f, indent=2)

# CSV format for analysis
df = pd.DataFrame(multi_source_dataset)
df.to_csv('comprehensive_dataset.csv', index=False)

# Parquet format for efficient storage
df.to_parquet('comprehensive_dataset.parquet')

print(f"Created dataset with {len(multi_source_dataset)} records")
print(f"Source breakdown: {df['source_type'].value_counts().to_dict()}")
```

### 2. Real-time Content Monitoring

```python
async def setup_content_monitoring(urls, check_interval=3600):
    """Set up real-time content monitoring with multiple archive services."""
    
    import schedule
    import threading
    
    def monitor_and_archive():
        """Monitor URLs and archive changes."""
        for url in urls:
            try:
                # Check current content
                current_response = requests.get(url, timeout=30)
                current_hash = hashlib.md5(current_response.content).hexdigest()
                
                # Compare with last known version
                last_hash_file = f"monitoring/{url.replace('/', '_')}_hash.txt"
                os.makedirs('monitoring', exist_ok=True)
                
                if os.path.exists(last_hash_file):
                    with open(last_hash_file, 'r') as f:
                        last_hash = f.read().strip()
                else:
                    last_hash = None
                
                # If content changed, archive it
                if current_hash != last_hash:
                    print(f"Content changed for {url}, archiving...")
                    
                    # Archive to multiple services
                    warc_path = processor.create_warc(url, options={'agent': 'wget'})
                    ia_url = archivenow.push(url, "ia")
                    is_url = archivenow.push(url, "is")
                    
                    # Update hash file
                    with open(last_hash_file, 'w') as f:
                        f.write(current_hash)
                    
                    print(f"Archived changed content:")
                    print(f"  - WARC: {warc_path}")
                    print(f"  - Internet Archive: {ia_url}")
                    print(f"  - Archive.is: {is_url}")
                else:
                    print(f"No changes detected for {url}")
                    
            except Exception as e:
                print(f"Monitoring error for {url}: {e}")
    
    # Schedule monitoring
    schedule.every(check_interval).seconds.do(monitor_and_archive)
    
    # Run monitoring in background
    def run_monitoring():
        while True:
            schedule.run_pending()
            time.sleep(60)
    
    monitoring_thread = threading.Thread(target=run_monitoring, daemon=True)
    monitoring_thread.start()
    
    return monitoring_thread

# Start monitoring important URLs
monitoring_urls = [
    "https://example.com",
    "https://important-news-site.com",
    "https://research-publication.org"
]

monitor_thread = await setup_content_monitoring(monitoring_urls, check_interval=3600)
print("Content monitoring started...")
```

## Performance and Optimization

### Parallel Processing Strategies

```python
import asyncio
import concurrent.futures
from functools import partial

async def parallel_scraping_pipeline(urls, max_workers=5):
    """Parallel web scraping with optimized resource usage."""
    
    # Separate URLs by type for optimized processing
    web_urls = [url for url in urls if not any(platform in url for platform in 
                ['youtube.com', 'vimeo.com', 'soundcloud.com', 'tiktok.com'])]
    media_urls = [url for url in urls if any(platform in url for platform in 
                 ['youtube.com', 'vimeo.com', 'soundcloud.com', 'tiktok.com'])]
    
    results = {'web': [], 'media': []}
    
    # Parallel web archiving
    web_tasks = []
    for url in web_urls:
        task = asyncio.create_task(processor.create_warc(
            url=url,
            options={'agent': 'wget', 'depth': 1}
        ))
        web_tasks.append(task)
    
    # Process web archives in parallel (limited concurrency)
    semaphore = asyncio.Semaphore(max_workers)
    
    async def limited_web_archive(url):
        async with semaphore:
            return await processor.create_warc(url, options={'agent': 'wget'})
    
    web_results = await asyncio.gather(
        *[limited_web_archive(url) for url in web_urls],
        return_exceptions=True
    )
    results['web'] = web_results
    
    # Parallel media downloads (with different limits for media)
    media_semaphore = asyncio.Semaphore(3)  # Lower limit for media downloads
    
    async def limited_media_download(url):
        async with media_semaphore:
            return await ytdlp_download_video(
                url=url,
                output_dir="parallel_downloads",
                quality="best[height<=720]"
            )
    
    media_results = await asyncio.gather(
        *[limited_media_download(url) for url in media_urls],
        return_exceptions=True
    )
    results['media'] = media_results
    
    return results

# Run parallel scraping
mixed_urls = [
    "https://example.com",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://blog.example.com",
    "https://vimeo.com/148751763"
]

parallel_results = await parallel_scraping_pipeline(mixed_urls, max_workers=3)
```

### Resource Management and Optimization

```python
# Monitor resource usage during scraping
import psutil
import time

class ResourceMonitor:
    """Monitor system resources during scraping operations."""
    
    def __init__(self, max_memory_percent=80, max_cpu_percent=90):
        self.max_memory = max_memory_percent
        self.max_cpu = max_cpu_percent
        self.monitoring = True
    
    def check_resources(self):
        """Check current resource usage."""
        memory_percent = psutil.virtual_memory().percent
        cpu_percent = psutil.cpu_percent(interval=1)
        
        return {
            'memory_percent': memory_percent,
            'cpu_percent': cpu_percent,
            'memory_ok': memory_percent < self.max_memory,
            'cpu_ok': cpu_percent < self.max_cpu
        }
    
    async def wait_for_resources(self, check_interval=30):
        """Wait until system resources are available."""
        while self.monitoring:
            status = self.check_resources()
            
            if status['memory_ok'] and status['cpu_ok']:
                return True
            else:
                print(f"High resource usage - Memory: {status['memory_percent']:.1f}%, CPU: {status['cpu_percent']:.1f}%")
                await asyncio.sleep(check_interval)

# Use resource monitoring in scraping pipeline
monitor = ResourceMonitor(max_memory_percent=85, max_cpu_percent=80)

async def resource_aware_scraping(urls):
    """Scraping with automatic resource management."""
    results = []
    
    for url in urls:
        # Wait for resources to be available
        await monitor.wait_for_resources()
        
        # Check resource status
        status = monitor.check_resources()
        print(f"Starting download - Memory: {status['memory_percent']:.1f}%, CPU: {status['cpu_percent']:.1f}%")
        
        # Proceed with download
        if 'youtube.com' in url:
            result = await ytdlp_download_video(url, "resource_managed_downloads")
        else:
            result = await processor.create_warc(url)
        
        results.append(result)
        
        # Brief pause between operations
        await asyncio.sleep(2)
    
    return results
```

## Error Handling and Reliability

### Robust Scraping with Retry Logic

```python
import asyncio
from functools import wraps

def retry_on_failure(max_retries=3, delay=5, exceptions=(Exception,)):
    """Decorator for retrying failed operations."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_retries - 1:
                        raise e
                    print(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay} seconds...")
                    await asyncio.sleep(delay * (attempt + 1))  # Exponential backoff
            return None
        return wrapper
    return decorator

@retry_on_failure(max_retries=3, delay=5)
async def reliable_video_download(url, output_dir):
    """Reliable video download with retry logic."""
    return await ytdlp_download_video(
        url=url,
        output_dir=output_dir,
        quality="best[height<=720]",
        timeout=300
    )

@retry_on_failure(max_retries=2, delay=10)
async def reliable_web_archive(url):
    """Reliable web archiving with retry logic."""
    return processor.create_warc(
        url=url,
        options={'agent': 'wget', 'timeout': 120}
    )

# Use reliable scraping
reliable_results = []
for url in urls:
    try:
        if 'youtube.com' in url:
            result = await reliable_video_download(url, "reliable_downloads")
        else:
            result = await reliable_web_archive(url)
        reliable_results.append(result)
    except Exception as e:
        print(f"Final failure for {url}: {e}")
        reliable_results.append({'status': 'failed', 'url': url, 'error': str(e)})
```

### Data Validation and Quality Control

```python
def validate_scraped_content(dataset_records):
    """Validate quality of scraped content."""
    
    validation_results = {
        'total_records': len(dataset_records),
        'valid_records': 0,
        'issues': []
    }
    
    for i, record in enumerate(dataset_records):
        issues = []
        
        # Check required fields
        required_fields = ['url', 'content', 'source_type']
        for field in required_fields:
            if not record.get(field):
                issues.append(f"Missing required field: {field}")
        
        # Content quality checks
        content = record.get('content', '')
        if len(content) < 100:
            issues.append("Content too short (<100 characters)")
        
        # URL validation
        url = record.get('url', '')
        if not url.startswith(('http://', 'https://')):
            issues.append("Invalid URL format")
        
        # File existence check for multimedia
        if record.get('source_type') == 'multimedia':
            file_path = record.get('file_path', '')
            if file_path and not os.path.exists(file_path):
                issues.append("Referenced file does not exist")
        
        if issues:
            validation_results['issues'].append({
                'record_index': i,
                'url': record.get('url', 'Unknown'),
                'issues': issues
            })
        else:
            validation_results['valid_records'] += 1
    
    validation_results['quality_score'] = validation_results['valid_records'] / validation_results['total_records'] * 100
    
    return validation_results

# Validate dataset quality
validation = validate_scraped_content(multi_source_dataset)
print(f"Dataset quality: {validation['quality_score']:.1f}%")
print(f"Valid records: {validation['valid_records']}/{validation['total_records']}")

if validation['issues']:
    print(f"Found {len(validation['issues'])} quality issues:")
    for issue in validation['issues'][:5]:  # Show first 5 issues
        print(f"  Record {issue['record_index']} ({issue['url']}): {', '.join(issue['issues'])}")
```

## Deployment and Production Considerations

### Scalable Scraping Infrastructure

```python
# Configuration for production-scale scraping
PRODUCTION_CONFIG = {
    'web_archiving': {
        'max_parallel_warc_creation': 5,
        'warc_timeout': 300,
        'retry_attempts': 3,
        'respect_robots_txt': True,
        'crawl_delay': 2,
        'user_agent': 'IPFS Datasets Production Bot 1.0'
    },
    'multimedia_scraping': {
        'max_parallel_downloads': 3,
        'download_timeout': 600,
        'quality_preference': 'best[height<=720]',
        'extract_metadata': True,
        'archive_downloaded_urls': True
    },
    'storage': {
        'use_ipfs': True,
        'pin_important_content': True,
        'backup_to_multiple_nodes': True,
        'compression_enabled': True
    },
    'monitoring': {
        'resource_monitoring': True,
        'error_tracking': True,
        'performance_metrics': True,
        'content_quality_checks': True
    }
}

# Production-ready scraping class
class ProductionWebScraper:
    """Production-grade web scraping with monitoring and reliability."""
    
    def __init__(self, config=PRODUCTION_CONFIG):
        self.config = config
        self.processor = WebArchiveProcessor()
        self.monitor = ResourceMonitor()
        self.error_log = []
        self.performance_metrics = {}
    
    async def scrape_with_monitoring(self, targets):
        """Scrape with comprehensive monitoring."""
        start_time = time.time()
        results = []
        
        for target in targets:
            target_start = time.time()
            
            try:
                # Wait for resources
                await self.monitor.wait_for_resources()
                
                # Execute scraping
                if target['type'] == 'web':
                    result = await self.reliable_web_archive(target['url'])
                elif target['type'] == 'media':
                    result = await self.reliable_media_download(target['url'])
                
                # Record performance
                duration = time.time() - target_start
                self.performance_metrics[target['url']] = {
                    'duration': duration,
                    'success': result.get('status') == 'success',
                    'size': result.get('file_size', 0)
                }
                
                results.append(result)
                
            except Exception as e:
                self.error_log.append({
                    'url': target['url'],
                    'error': str(e),
                    'timestamp': time.time()
                })
                results.append({'status': 'error', 'url': target['url'], 'error': str(e)})
        
        # Generate performance report
        total_duration = time.time() - start_time
        success_count = len([r for r in results if r.get('status') == 'success'])
        
        print(f"\\nScraping completed in {total_duration:.1f} seconds")
        print(f"Success rate: {success_count}/{len(targets)} ({success_count/len(targets)*100:.1f}%)")
        print(f"Errors logged: {len(self.error_log)}")
        
        return results
    
    @retry_on_failure(max_retries=3, delay=5)
    async def reliable_web_archive(self, url):
        return self.processor.create_warc(url, options=self.config['web_archiving'])
    
    @retry_on_failure(max_retries=3, delay=10)
    async def reliable_media_download(self, url):
        return await ytdlp_download_video(url, "production_downloads", **self.config['multimedia_scraping'])

# Use production scraper
production_scraper = ProductionWebScraper()
production_targets = [
    {'type': 'web', 'url': 'https://example.com'},
    {'type': 'media', 'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'}
]

production_results = await production_scraper.scrape_with_monitoring(production_targets)
```

This comprehensive guide covers all major web scraping and archiving capabilities in IPFS Datasets Python, from basic operations to production-scale deployments with monitoring and reliability features.