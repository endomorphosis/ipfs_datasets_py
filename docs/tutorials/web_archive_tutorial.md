# Web Archive Processing Tutorial

This tutorial demonstrates how to archive websites, process web archives, and build datasets from web content using IPFS Datasets Python.

## Table of Contents

1. [Introduction](#introduction)
2. [Prerequisites](#prerequisites)
3. [Setting Up](#setting-up)
4. [Archiving Websites](#archiving-websites)
5. [Indexing WARC Files](#indexing-warc-files)
6. [Extracting Structured Data](#extracting-structured-data)
7. [Creating Searchable Datasets](#creating-searchable-datasets)
8. [Advanced Techniques](#advanced-techniques)
9. [Complete Example](#complete-example)

## Introduction

Web archives provide valuable historical data that can be processed into structured datasets. IPFS Datasets Python integrates with InterPlanetary Wayback (IPWB) and ArchiveNow to provide a complete web archiving and processing solution.

## Prerequisites

- IPFS Datasets Python installed with web archive dependencies:
  ```bash
  pip install ipfs-datasets-py[webarchive]
  ```
- IPFS daemon running (for IPWB functionality)
- Basic understanding of WARC and CDXJ file formats

## Setting Up

First, let's set up our environment for web archive processing:

```python
from ipfs_datasets_py.web_archive_utils import WebArchiveProcessor
import os
import tempfile

# Initialize the web archive processor
processor = WebArchiveProcessor()

# Set up directories for archives and indexes
archive_dir = "web_archives"
index_dir = "archive_indexes"
dataset_dir = "extracted_datasets"

os.makedirs(archive_dir, exist_ok=True)
os.makedirs(index_dir, exist_ok=True)
os.makedirs(dataset_dir, exist_ok=True)

print("Web archive processing environment ready!")
```

## Archiving Websites

### Single Website Archiving

Archive a website using ArchiveNow with different agents:

```python
# Archive a simple website with wget (best for static content)
warc_path_static = processor.create_warc(
    url="https://example.com",
    output_path=f"{archive_dir}/example_static.warc.gz",
    options={
        "agent": "wget",
        "depth": 2,
        "compress": True,
        "user_agent": "Web Archive Bot 1.0"
    }
)
print(f"Static site archived to: {warc_path_static}")

# Archive a dynamic website with squidwarc (better for JavaScript-heavy sites)
warc_path_dynamic = processor.create_warc(
    url="https://news.ycombinator.com",
    output_path=f"{archive_dir}/hnews_dynamic.warc.gz",
    options={
        "agent": "squidwarc",
        "depth": 1,
        "compress": True,
        "include_patterns": ["*/item*", "*/front*"],
        "exclude_patterns": ["*/submit*", "*/login*"]
    }
)
print(f"Dynamic site archived to: {warc_path_dynamic}")
```

### Archiving to Multiple Services

Use ArchiveNow to push content to multiple web archives simultaneously:

```python
from archivenow import archivenow

# Archive to Internet Archive
ia_result = archivenow.push("https://example.com", "ia")
print(f"Internet Archive URL: {ia_result}")

# Archive to Archive.today (archive.is)
is_result = archivenow.push("https://example.com", "is")  
print(f"Archive.today URL: {is_result}")

# Archive to Perma.cc
cc_result = archivenow.push("https://example.com", "cc")
print(f"Perma.cc URL: {cc_result}")

# Create local WARC and archive to multiple services
warc_result = archivenow.push("https://example.com", "warc", {"warc": "example_multi"})
ia_result = archivenow.push("https://example.com", "ia")
is_result = archivenow.push("https://example.com", "is")

print(f"WARC file: {warc_result}")
print(f"Internet Archive: {ia_result}")
print(f"Archive.today: {is_result}")
```

### Batch Website Archiving

Archive multiple websites efficiently:

```python
websites_to_archive = [
    "https://example.com/page1",
    "https://example.com/page2", 
    "https://blog.example.com",
    "https://docs.example.com"
]

archived_sites = []
for url in websites_to_archive:
    try:
        warc_path = processor.create_warc(
            url=url,
            output_path=f"{archive_dir}/{url.split('//')[1].replace('/', '_')}.warc.gz",
            options={
                "agent": "wget",
                "depth": 1,
                "compress": True,
                "delay": 2  # Be respectful to servers
            }
        )
        archived_sites.append((url, warc_path))
        print(f"✅ Archived: {url}")
    except Exception as e:
        print(f"❌ Failed to archive {url}: {e}")

print(f"Successfully archived {len(archived_sites)} websites")
```

## Indexing WARC Files

After archiving, we'll index the WARC files with IPWB for decentralized access:

```python
# Index a WARC file to IPFS using IPWB
try:
    index_result = processor.index_warc(
        warc_path=warc_path_static,
        output_path=f"{index_dir}/example_static.cdxj"
    )
    
    print(f"CDXJ index created: {index_result['cdxj_path']}")
    print(f"IPFS hash: {index_result['ipfs_hash']}")
    print(f"Record count: {index_result['record_count']}")
    print(f"URL count: {index_result['url_count']}")
    
except ImportError:
    print("IPWB not available. Install with: pip install ipwb")
    # Fallback: process WARC directly without IPFS indexing
    print("Proceeding with direct WARC processing...")

# Index multiple WARC files
cdxj_files = []
for url, warc_path in archived_sites:
    try:
        cdxj_path = f"{index_dir}/{Path(warc_path).stem}.cdxj"
        index_result = processor.index_warc(
            warc_path=warc_path,
            output_path=cdxj_path
        )
        cdxj_files.append(cdxj_path)
        print(f"✅ Indexed: {warc_path}")
    except Exception as e:
        print(f"❌ Failed to index {warc_path}: {e}")

print(f"Created {len(cdxj_files)} CDXJ indexes")
```

### Understanding CDXJ Format

CDXJ (Canonical URL and Timestamp with JSON) files contain archive indexes:

```python
# Read and examine a CDXJ file
if cdxj_files:
    with open(cdxj_files[0], 'r') as f:
        # CDXJ format: URL timestamp JSON-metadata
        first_lines = [f.readline().strip() for _ in range(3)]
        
    print("Sample CDXJ entries:")
    for line in first_lines:
        if line:
            parts = line.split(' ', 2)
            url, timestamp, metadata = parts[0], parts[1], parts[2] if len(parts) > 2 else ""
            print(f"  URL: {url}")
            print(f"  Timestamp: {timestamp}")
            print(f"  Metadata: {metadata[:100]}...")
            print()
```

## Extracting Structured Data

Now, let's extract structured data from the web archives:

```python
# Extract text content from WARC files
text_data = []
for url, warc_path in archived_sites:
    try:
        extracted_text = processor.extract_text_from_warc(warc_path)
        text_data.extend(extracted_text)
        print(f"✅ Extracted text from: {warc_path}")
    except Exception as e:
        print(f"❌ Failed to extract text from {warc_path}: {e}")

print(f"Extracted text from {len(text_data)} web pages")

# Extract link relationships
link_data = []
for url, warc_path in archived_sites:
    try:
        extracted_links = processor.extract_links_from_warc(warc_path)
        link_data.extend(extracted_links)
        print(f"✅ Extracted links from: {warc_path}")
    except Exception as e:
        print(f"❌ Failed to extract links from {warc_path}: {e}")

print(f"Extracted {len(link_data)} link relationships")

# Extract metadata from archives
metadata_list = []
for url, warc_path in archived_sites:
    try:
        extracted_metadata = processor.extract_metadata_from_warc(warc_path)
        metadata_list.extend(extracted_metadata)
        print(f"✅ Extracted metadata from: {warc_path}")
    except Exception as e:
        print(f"❌ Failed to extract metadata from {warc_path}: {e}")

print(f"Extracted metadata from {len(metadata_list)} records")

# Sample extracted data
if text_data:
    print("\\nSample extracted text:")
    sample_text = text_data[0]
    print(f"  URL: {sample_text.get('url', 'N/A')}")
    print(f"  Title: {sample_text.get('title', 'N/A')}")
    print(f"  Text: {sample_text.get('text', 'N/A')[:200]}...")
```

### Working with Internet Archive and Common Crawl

Access existing web archives from major sources:

```python
# Query Internet Archive Wayback Machine
def query_wayback_machine(url, from_date="20200101", to_date="20240101"):
    """Query Wayback Machine for historical captures."""
    import requests
    
    # CDX API endpoint for Wayback Machine
    cdx_url = f"http://web.archive.org/cdx/search/cdx"
    params = {
        'url': url,
        'from': from_date,
        'to': to_date,
        'output': 'json',
        'limit': 100
    }
    
    try:
        response = requests.get(cdx_url, params=params)
        response.raise_for_status()
        
        data = response.json()
        if len(data) > 1:  # First row is headers
            captures = data[1:]  # Skip header row
            print(f"Found {len(captures)} captures for {url}")
            return captures
        else:
            print(f"No captures found for {url}")
            return []
            
    except Exception as e:
        print(f"Error querying Wayback Machine: {e}")
        return []

# Example: Query captures for a domain
captures = query_wayback_machine("example.com")
if captures:
    print("Sample captures:")
    for capture in captures[:3]:
        timestamp, original, mimetype, statuscode, digest, length = capture[:6]
        print(f"  {timestamp}: {original} ({mimetype})")

# Query Common Crawl data
def query_common_crawl(domain, crawl_id="CC-MAIN-2024-10"):
    """Query Common Crawl for domain content."""
    import requests
    
    # Common Crawl Index API
    cc_url = f"https://index.commoncrawl.org/{crawl_id}-index"
    params = {
        'url': f"*.{domain}/*",
        'output': 'json',
        'limit': 50
    }
    
    try:
        response = requests.get(cc_url, params=params)
        response.raise_for_status()
        
        results = []
        for line in response.text.strip().split('\\n'):
            if line:
                results.append(eval(line))  # JSON per line
        
        print(f"Found {len(results)} Common Crawl records for {domain}")
        return results
        
    except Exception as e:
        print(f"Error querying Common Crawl: {e}")
        return []

# Example: Query Common Crawl for domain
cc_results = query_common_crawl("example.com")
if cc_results:
    print("Sample Common Crawl records:")
    for result in cc_results[:3]:
        print(f"  URL: {result.get('url', 'N/A')}")
        print(f"  Timestamp: {result.get('timestamp', 'N/A')}")
```

## Creating Searchable Datasets

We'll create searchable datasets from the extracted data:

```python
import json
import pandas as pd
from pathlib import Path

# Convert extracted data to pandas DataFrame for analysis
def create_searchable_dataset(text_data, link_data, metadata_list):
    """Create a searchable dataset from extracted web archive data."""
    
    # Combine all data sources
    dataset_records = []
    
    # Process text data
    for record in text_data:
        dataset_record = {
            'url': record.get('url', ''),
            'title': record.get('title', ''),
            'text_content': record.get('text', ''),
            'content_length': len(record.get('text', '')),
            'timestamp': record.get('timestamp', ''),
            'source': 'text_extraction',
            'links_out': [],
            'metadata': {}
        }
        dataset_records.append(dataset_record)
    
    # Enrich with link data
    link_lookup = {}
    for link_record in link_data:
        source_url = link_record.get('source_url', '')
        if source_url not in link_lookup:
            link_lookup[source_url] = []
        link_lookup[source_url].append(link_record.get('target_url', ''))
    
    # Add links to dataset records
    for record in dataset_records:
        record['links_out'] = link_lookup.get(record['url'], [])
        record['outlink_count'] = len(record['links_out'])
    
    # Enrich with metadata
    metadata_lookup = {}
    for meta_record in metadata_list:
        url = meta_record.get('url', '')
        metadata_lookup[url] = meta_record
    
    for record in dataset_records:
        record['metadata'] = metadata_lookup.get(record['url'], {})
        
    return dataset_records

# Create the searchable dataset
dataset_records = create_searchable_dataset(text_data, link_data, metadata_list)

# Save as JSON for further processing
dataset_path = f"{dataset_dir}/web_archive_dataset.json"
with open(dataset_path, 'w') as f:
    json.dump(dataset_records, f, indent=2)

print(f"Searchable dataset created: {dataset_path}")
print(f"Total records: {len(dataset_records)}")

# Create DataFrame for analysis
df = pd.DataFrame(dataset_records)
print(f"Dataset columns: {list(df.columns)}")
print(f"Text content summary:")
print(f"  - Average content length: {df['content_length'].mean():.0f} characters")
print(f"  - Total outlinks: {df['outlink_count'].sum()}")
print(f"  - Unique domains: {len(df['url'].apply(lambda x: x.split('/')[2] if len(x.split('/')) > 2 else '').unique())}")

# Save as CSV for spreadsheet analysis
csv_path = f"{dataset_dir}/web_archive_dataset.csv"
df.to_csv(csv_path, index=False)
print(f"CSV dataset saved: {csv_path}")
```

### Creating Vector Embeddings for Semantic Search

```python
# Note: This requires sentence-transformers or similar embedding library
try:
    from sentence_transformers import SentenceTransformer
    
    # Load embedding model
    model = SentenceTransformer('all-MiniLM-L6-v2')
    
    # Create embeddings for page titles and content
    texts_for_embedding = []
    for record in dataset_records[:10]:  # Sample first 10 for demo
        text = f"{record['title']} {record['text_content'][:500]}"  # Title + content sample
        texts_for_embedding.append(text)
    
    # Generate embeddings
    embeddings = model.encode(texts_for_embedding)
    print(f"Generated {len(embeddings)} embeddings of dimension {embeddings[0].shape}")
    
    # Save embeddings for later use
    import numpy as np
    np.save(f"{dataset_dir}/web_archive_embeddings.npy", embeddings)
    
except ImportError:
    print("sentence-transformers not available. Install with: pip install sentence-transformers")
    print("Skipping embedding generation...")
```

## Advanced Techniques

Here are some advanced techniques for web archive processing:

### 1. Content Deduplication and Analysis

```python
import hashlib
from collections import defaultdict

def deduplicate_content(dataset_records):
    """Remove duplicate content based on text content hashes."""
    content_hashes = {}
    unique_records = []
    duplicate_count = 0
    
    for record in dataset_records:
        content = record.get('text_content', '')
        content_hash = hashlib.md5(content.encode()).hexdigest()
        
        if content_hash not in content_hashes:
            content_hashes[content_hash] = record['url']
            unique_records.append(record)
        else:
            duplicate_count += 1
            print(f"Duplicate found: {record['url']} (original: {content_hashes[content_hash]})")
    
    print(f"Removed {duplicate_count} duplicates, kept {len(unique_records)} unique records")
    return unique_records

# Apply deduplication
unique_records = deduplicate_content(dataset_records)
```

### 2. Language Detection and Filtering

```python
try:
    from langdetect import detect, LangDetectError
    
    def add_language_detection(records):
        """Add language detection to records."""
        for record in records:
            text = record.get('text_content', '')
            if len(text) > 50:  # Need minimum text for detection
                try:
                    language = detect(text)
                    record['detected_language'] = language
                except LangDetectError:
                    record['detected_language'] = 'unknown'
            else:
                record['detected_language'] = 'insufficient_text'
        return records
    
    # Add language detection
    records_with_lang = add_language_detection(unique_records)
    
    # Filter for English content
    english_records = [r for r in records_with_lang if r.get('detected_language') == 'en']
    print(f"Found {len(english_records)} English records out of {len(records_with_lang)} total")
    
except ImportError:
    print("langdetect not available. Install with: pip install langdetect")
    english_records = unique_records
```

### 3. Archive.is Integration

```python
import requests
import time

def archive_to_archive_is(urls):
    """Archive URLs to archive.is (archive.today)."""
    archived_urls = []
    
    for url in urls:
        try:
            # Submit URL to archive.is
            response = requests.post(
                'https://archive.is/submit/',
                data={'url': url},
                headers={'User-Agent': 'Web Archive Bot 1.0'},
                timeout=30
            )
            
            if response.status_code == 200:
                # Extract archive URL from response
                archive_url = response.url
                archived_urls.append({
                    'original_url': url,
                    'archive_url': archive_url,
                    'service': 'archive.is',
                    'timestamp': time.time()
                })
                print(f"✅ Archived to archive.is: {url} -> {archive_url}")
            else:
                print(f"❌ Failed to archive {url} (status: {response.status_code})")
                
        except Exception as e:
            print(f"❌ Error archiving {url}: {e}")
        
        # Be respectful to the service
        time.sleep(2)
    
    return archived_urls

# Archive sample URLs to archive.is
sample_urls = [record['url'] for record in dataset_records[:3]]  # First 3 URLs
archive_is_results = archive_to_archive_is(sample_urls)
```

### 4. Temporal Analysis of Web Content

```python
from datetime import datetime

def analyze_temporal_patterns(records):
    """Analyze temporal patterns in archived content."""
    temporal_data = defaultdict(list)
    
    for record in records:
        timestamp = record.get('timestamp', '')
        if timestamp:
            # Convert WARC timestamp format to datetime
            try:
                if len(timestamp) >= 14:
                    dt = datetime.strptime(timestamp[:14], '%Y%m%d%H%M%S')
                    month_key = dt.strftime('%Y-%m')
                    temporal_data[month_key].append(record)
            except ValueError:
                pass
    
    print("Temporal distribution of archived content:")
    for month, records in sorted(temporal_data.items()):
        print(f"  {month}: {len(records)} pages")
    
    return temporal_data

# Analyze temporal patterns
temporal_patterns = analyze_temporal_patterns(dataset_records)
```

### 5. Cross-Archive Content Linking

```python
def cross_reference_archives(local_records, wayback_captures):
    """Cross-reference local archives with Wayback Machine captures."""
    cross_refs = []
    
    local_urls = {record['url'] for record in local_records}
    
    for capture in wayback_captures:
        if len(capture) >= 2:
            timestamp, original_url = capture[0], capture[1]
            if original_url in local_urls:
                cross_refs.append({
                    'url': original_url,
                    'local_archive': True,
                    'wayback_timestamp': timestamp,
                    'wayback_url': f"http://web.archive.org/web/{timestamp}/{original_url}"
                })
    
    print(f"Found {len(cross_refs)} URLs in both local and Wayback archives")
    return cross_refs

# Cross-reference if we have wayback data
if 'captures' in locals() and captures:
    cross_references = cross_reference_archives(dataset_records, captures)
```

## Complete Example

Finally, here's a complete example that ties everything together:

```python
#!/usr/bin/env python3
"""
Complete Web Archive Processing Example

This example demonstrates a full workflow for archiving websites,
processing web archives, and creating structured datasets.
"""

import os
import json
import time
from pathlib import Path
from ipfs_datasets_py.web_archive_utils import WebArchiveProcessor

def complete_web_archive_workflow():
    """Complete workflow for web archive processing."""
    
    # 1. Setup
    print("🚀 Starting complete web archive workflow...")
    processor = WebArchiveProcessor()
    
    # Create directories
    base_dir = "complete_archive_example"
    archive_dir = f"{base_dir}/archives"
    index_dir = f"{base_dir}/indexes" 
    dataset_dir = f"{base_dir}/datasets"
    
    for directory in [archive_dir, index_dir, dataset_dir]:
        os.makedirs(directory, exist_ok=True)
    
    # 2. Archive multiple websites
    print("\\n📦 Archiving websites...")
    websites = [
        {"url": "https://example.com", "agent": "wget"},
        {"url": "https://httpbin.org", "agent": "wget"},
    ]
    
    archived_files = []
    for site in websites:
        try:
            warc_path = processor.create_warc(
                url=site["url"],
                output_path=f"{archive_dir}/{site['url'].split('//')[1].replace('/', '_')}.warc.gz",
                options={
                    "agent": site["agent"],
                    "depth": 1,
                    "compress": True,
                    "delay": 1
                }
            )
            archived_files.append(warc_path)
            print(f"✅ Archived: {site['url']}")
            time.sleep(2)  # Be respectful
        except Exception as e:
            print(f"❌ Failed to archive {site['url']}: {e}")
    
    # 3. Index archives to IPFS
    print("\\n🔍 Indexing archives...")
    cdxj_files = []
    for warc_path in archived_files:
        try:
            cdxj_path = f"{index_dir}/{Path(warc_path).stem}.cdxj"
            index_result = processor.index_warc(warc_path, cdxj_path)
            cdxj_files.append(cdxj_path)
            print(f"✅ Indexed: {Path(warc_path).name}")
        except Exception as e:
            print(f"❌ Failed to index {warc_path}: {e}")
    
    # 4. Extract structured data
    print("\\n📊 Extracting structured data...")
    all_text_data = []
    all_link_data = []
    all_metadata = []
    
    for warc_path in archived_files:
        try:
            # Extract text
            text_data = processor.extract_text_from_warc(warc_path)
            all_text_data.extend(text_data)
            
            # Extract links
            link_data = processor.extract_links_from_warc(warc_path)
            all_link_data.extend(link_data)
            
            # Extract metadata
            metadata = processor.extract_metadata_from_warc(warc_path)
            all_metadata.extend(metadata)
            
            print(f"✅ Processed: {Path(warc_path).name}")
        except Exception as e:
            print(f"❌ Failed to process {warc_path}: {e}")
    
    # 5. Create comprehensive dataset
    print("\\n🏗️ Building final dataset...")
    final_dataset = []
    
    for text_record in all_text_data:
        # Find corresponding metadata
        url = text_record.get('url', '')
        metadata = next((m for m in all_metadata if m.get('url') == url), {})
        
        # Find outbound links
        outbound_links = [l.get('target_url', '') for l in all_link_data 
                         if l.get('source_url') == url]
        
        # Combine into final record
        final_record = {
            'url': url,
            'title': text_record.get('title', ''),
            'content': text_record.get('text', ''),
            'content_length': len(text_record.get('text', '')),
            'outbound_links': outbound_links,
            'link_count': len(outbound_links),
            'mime_type': metadata.get('mime_type', ''),
            'status_code': metadata.get('status_code', ''),
            'timestamp': metadata.get('timestamp', ''),
            'content_encoding': metadata.get('encoding', ''),
            'domain': url.split('/')[2] if len(url.split('/')) > 2 else '',
            'path': '/' + '/'.join(url.split('/')[3:]) if len(url.split('/')) > 3 else '/'
        }
        final_dataset.append(final_record)
    
    # 6. Save final dataset in multiple formats
    print("\\n💾 Saving final dataset...")
    
    # JSON format
    json_path = f"{dataset_dir}/final_web_archive_dataset.json"
    with open(json_path, 'w') as f:
        json.dump(final_dataset, f, indent=2)
    
    # CSV format
    import pandas as pd
    df = pd.DataFrame(final_dataset)
    csv_path = f"{dataset_dir}/final_web_archive_dataset.csv"
    df.to_csv(csv_path, index=False)
    
    # Summary statistics
    print(f"\\n📈 Dataset Summary:")
    print(f"  - Total pages: {len(final_dataset)}")
    print(f"  - Unique domains: {len(df['domain'].unique())}")
    print(f"  - Total content: {df['content_length'].sum():,} characters")
    print(f"  - Average links per page: {df['link_count'].mean():.1f}")
    print(f"  - JSON dataset: {json_path}")
    print(f"  - CSV dataset: {csv_path}")
    
    return final_dataset

# Run the complete workflow
if __name__ == "__main__":
    final_dataset = complete_web_archive_workflow()
    print("\\n🎉 Complete web archive workflow finished!")
```

### Integration with IPFS Datasets

```python
# Convert to IPFS Datasets format for distributed storage
try:
    from ipfs_datasets_py import ipfs_datasets_py
    
    # Initialize IPFS datasets
    ipfs_dataset = ipfs_datasets_py(resources={"endpoint": "https://ipfs.io"})
    
    # Upload dataset to IPFS
    dataset_path = f"{dataset_dir}/final_web_archive_dataset.json"
    cid = ipfs_dataset.upload_file(dataset_path)
    
    print(f"📤 Dataset uploaded to IPFS: {cid}")
    print(f"🌐 Access via: https://ipfs.io/ipfs/{cid}")
    
except Exception as e:
    print(f"IPFS upload not available: {e}")
```

This tutorial demonstrated how to archive websites, process web archives, and create structured datasets from web content using IPFS Datasets Python and the integrated web archive tools.