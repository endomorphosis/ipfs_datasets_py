# GraphRAG Website Processing Tutorial

This tutorial demonstrates how to use the comprehensive GraphRAG website processing system to archive entire websites, extract content from all media types, and create searchable knowledge systems.

## Overview

The GraphRAG Website Processing system provides end-to-end capabilities for:

1. **Website Archiving** - Archive websites to IPFS and external services
2. **Content Discovery** - Find all content types (HTML, PDFs, media files)
3. **Multi-Modal Processing** - Extract text from all content types including audio/video transcription
4. **Knowledge Graph Extraction** - Build structured knowledge from content
5. **GraphRAG Search** - Semantic search combining vector similarity with graph reasoning

## Quick Start

### Basic Website Processing

```python
import asyncio
from ipfs_datasets_py.website_graphrag_processor import WebsiteGraphRAGProcessor

# Initialize the processor
processor = WebsiteGraphRAGProcessor()

# Process a website into GraphRAG system
async def main():
    graphrag_system = await processor.process_website(
        url="https://example.com",
        crawl_depth=2,
        include_media=True,
        archive_services=['ia', 'is'],  # Internet Archive and Archive.is
        enable_graphrag=True
    )
    
    print(f"Successfully processed: {graphrag_system.url}")
    print(f"Content overview: {graphrag_system.get_content_overview()}")
    
    # Search the processed content
    results = graphrag_system.query(
        "What are the main topics discussed on this website?",
        max_results=10
    )
    
    print(f"\nFound {results.total_results} results:")
    for i, result in enumerate(results.results):
        print(f"{i+1}. {result.title}")
        print(f"   Type: {result.content_type}")
        print(f"   Score: {result.relevance_score:.3f}")
        print(f"   Snippet: {result.content_snippet[:100]}...")
        print()

# Run the example
asyncio.run(main())
```

## Detailed Usage Examples

### 1. Website Content Discovery

```python
from ipfs_datasets_py.content_discovery import ContentDiscoveryEngine

# Initialize content discovery
discovery = ContentDiscoveryEngine()

# Discover all content types in a website archive
async def discover_website_content():
    # Assuming you have a WARC file from website archiving
    manifest = await discovery.discover_content("website_archive.warc")
    
    print(f"Discovered content in {manifest.base_url}:")
    print(f"  HTML pages: {len(manifest.html_pages)}")
    print(f"  PDF documents: {len(manifest.pdf_documents)}")
    print(f"  Media files: {len(manifest.media_files)}")
    print(f"  Total assets: {manifest.total_assets}")
    
    # Show details of media files found
    for media in manifest.media_files:
        print(f"  {media.content_type}: {media.url}")
        if media.metadata:
            print(f"    Metadata: {media.metadata}")

asyncio.run(discover_website_content())
```

### 2. Multi-Modal Content Processing

```python
from ipfs_datasets_py.multimodal_processor import MultiModalContentProcessor

# Initialize content processor
processor = MultiModalContentProcessor({
    'transcription_model': 'base',  # Whisper model for audio/video
    'max_text_length': 50000,
    'enable_ocr': True,  # OCR for images and PDFs
    'embedding_model': 'sentence-transformers/all-MiniLM-L6-v2'
})

async def process_all_content_types():
    # Process discovered content
    processed_batch = await processor.process_content_batch(
        content_manifest=manifest,
        include_embeddings=True,
        include_media=True  # Process audio, video, images
    )
    
    print(f"Processing results:")
    print(f"  Total items processed: {processed_batch.total_items}")
    print(f"  Success rate: {processed_batch.success_rate:.1f}%")
    print(f"  Processing stats: {processed_batch.processing_stats}")
    
    # Show processed content by type
    html_items = [item for item in processed_batch.processed_items if item.content_type == 'html']
    pdf_items = [item for item in processed_batch.processed_items if item.content_type == 'pdf']
    media_items = [item for item in processed_batch.processed_items if item.content_type in ['audio', 'video']]
    
    print(f"\nHTML Content ({len(html_items)} items):")
    for item in html_items:
        print(f"  {item.source_url}: {item.text_length} characters")
    
    print(f"\nPDF Content ({len(pdf_items)} items):")  
    for item in pdf_items:
        print(f"  {item.source_url}: {item.text_length} characters")
        
    print(f"\nMedia Content ({len(media_items)} items):")
    for item in media_items:
        print(f"  {item.source_url}: {item.text_length} characters (transcribed)")

asyncio.run(process_all_content_types())
```

### 3. Knowledge Graph Extraction

```python
from ipfs_datasets_py.knowledge_graph_extraction import KnowledgeGraphExtractor

# Extract knowledge graph from all processed content
extractor = KnowledgeGraphExtractor()

# Combine all text content
combined_text = "\n\n".join([
    item.text_content for item in processed_batch.processed_items
    if item.text_content
])

# Extract knowledge graph
knowledge_graph = extractor.extract_graph_from_text(
    text=combined_text,
    confidence_threshold=0.7,
    max_entities=100,
    max_relationships=200
)

print(f"Knowledge Graph Statistics:")
print(f"  Entities: {len(knowledge_graph.entities)}")
print(f"  Relationships: {len(knowledge_graph.relationships)}")

# Show top entities by confidence
top_entities = sorted(knowledge_graph.entities, key=lambda e: e.confidence, reverse=True)[:10]
print(f"\nTop 10 Entities:")
for entity in top_entities:
    print(f"  {entity.name} ({entity.entity_type}) - Confidence: {entity.confidence:.3f}")

# Show relationships
print(f"\nSample Relationships:")
for rel in knowledge_graph.relationships[:5]:
    print(f"  {rel.source_entity.name} --[{rel.relationship_type}]--> {rel.target_entity.name}")
```

### 4. Complete GraphRAG System

```python
from ipfs_datasets_py.website_graphrag_system import WebsiteGraphRAGSystem

# Create complete GraphRAG system
graphrag_system = WebsiteGraphRAGSystem(
    url="https://example.com",
    content_manifest=manifest,
    processed_content=processed_batch,
    knowledge_graph=knowledge_graph,
    graphrag=None  # Will use vector search fallback
)

# Advanced search capabilities
async def demonstrate_search_features():
    
    # 1. General semantic search
    print("=== General Search ===")
    results = graphrag_system.query("artificial intelligence machine learning")
    for result in results.results[:3]:
        print(f"- {result.title} ({result.content_type})")
        print(f"  Score: {result.relevance_score:.3f}")
        print(f"  {result.content_snippet[:100]}...")
        print()
    
    # 2. Content-type filtered search
    print("=== PDF-only Search ===")
    pdf_results = graphrag_system.query(
        "research methodology", 
        content_types=['pdf'],
        max_results=5
    )
    print(f"Found {pdf_results.total_results} PDF results")
    
    # 3. Search within content type
    print("=== HTML Content Search ===")
    html_items = graphrag_system.search_by_content_type('html', query="tutorial")
    print(f"Found {len(html_items)} HTML pages with 'tutorial'")
    
    # 4. Find related content
    print("=== Related Content ===")
    if results.results:
        first_result_url = results.results[0].source_url
        related = graphrag_system.get_related_content(first_result_url, max_related=3)
        print(f"Content related to {first_result_url}:")
        for item in related:
            print(f"  - {item.source_url}")
            print(f"    Similarity: {item.metadata.get('similarity_score', 0):.3f}")

asyncio.run(demonstrate_search_features())
```

## Advanced Features

### 1. Batch Website Processing

```python
# Process multiple websites simultaneously
async def process_multiple_websites():
    urls = [
        "https://example.com",
        "https://docs.python.org",
        "https://www.tensorflow.org",
        "https://pytorch.org"
    ]
    
    # Configure for batch processing
    config = WebsiteProcessingConfig(
        max_parallel_processing=4,
        crawl_depth=1,  # Shallow crawl for speed
        include_media=True,
        archive_services=['ia']  # Just Internet Archive
    )
    
    processor = WebsiteGraphRAGProcessor(config=config)
    
    # Process all websites
    systems = await processor.process_multiple_websites(urls)
    
    print(f"Successfully processed {len(systems)} websites:")
    for system in systems:
        overview = system.get_content_overview()
        print(f"  {system.url}: {overview['discovery_stats']['total']} items")
    
    return systems

batch_systems = asyncio.run(process_multiple_websites())
```

### 2. Cross-Website Search

```python
# Search across multiple processed websites
def search_across_websites(systems, query):
    all_results = []
    
    for system in systems:
        results = system.query(query, max_results=5)
        for result in results.results:
            result.metadata['source_website'] = system.url
            all_results.append(result)
    
    # Sort all results by relevance
    all_results.sort(key=lambda r: r.relevance_score, reverse=True)
    
    print(f"Cross-website search results for '{query}':")
    for i, result in enumerate(all_results[:10]):
        print(f"{i+1}. {result.title}")
        print(f"   Website: {result.metadata['source_website']}")
        print(f"   Type: {result.content_type}")
        print(f"   Score: {result.relevance_score:.3f}")
        print()
    
    return all_results

# Search across all processed websites
cross_results = search_across_websites(batch_systems, "neural networks deep learning")
```

### 3. Dataset Export and Analysis

```python
# Export processed content as datasets
async def export_and_analyze():
    for system in batch_systems:
        # Export to JSON
        json_file = system.export_dataset(
            output_format="json",
            include_embeddings=True
        )
        print(f"Exported {system.url} to {json_file}")
        
        # Get detailed statistics
        overview = system.get_content_overview()
        print(f"Statistics for {system.url}:")
        print(f"  Total pages: {overview['discovery_stats']['html_pages']}")
        print(f"  PDF documents: {overview['discovery_stats']['pdf_documents']}")
        print(f"  Media files: {overview['discovery_stats']['media_files']}")
        print(f"  Knowledge graph entities: {overview['knowledge_graph_stats']['entities']}")
        print()

asyncio.run(export_and_analyze())
```

### 4. Real-time Content Monitoring

```python
# Monitor websites for changes and update GraphRAG systems
async def monitor_website_changes():
    urls_to_monitor = ["https://blog.example.com", "https://news.example.com"]
    
    # Initial processing
    initial_systems = {}
    for url in urls_to_monitor:
        system = await processor.process_website(url)
        initial_systems[url] = system
    
    # Check for changes (in a real application, this would run periodically)
    import time
    while True:
        print("Checking for website updates...")
        
        for url in urls_to_monitor:
            try:
                # Re-process website
                updated_system = await processor.process_website(url)
                
                # Compare content counts
                old_overview = initial_systems[url].get_content_overview()
                new_overview = updated_system.get_content_overview()
                
                old_total = old_overview['discovery_stats']['total']
                new_total = new_overview['discovery_stats']['total']
                
                if new_total > old_total:
                    print(f"New content detected on {url}: {new_total - old_total} new items")
                    initial_systems[url] = updated_system  # Update cached system
                else:
                    print(f"No changes detected on {url}")
                    
            except Exception as e:
                print(f"Error checking {url}: {e}")
        
        # Wait before next check (1 hour in production)
        await asyncio.sleep(3600)

# Run monitoring (this would typically run as a background service)
# asyncio.run(monitor_website_changes())
```

## Configuration Options

### Website Processing Configuration

```python
from ipfs_datasets_py.website_graphrag_processor import WebsiteProcessingConfig

# Create custom configuration
config = WebsiteProcessingConfig(
    # Archive settings
    archive_services=['ia', 'is', 'cc'],  # Multiple archive services
    crawl_depth=3,                        # Deep crawl
    include_robots_txt=True,              # Respect robots.txt
    
    # Content processing
    include_media=True,                   # Process audio/video/images
    max_file_size_mb=500,                 # Maximum file size to process
    supported_media_types=[
        'audio/mpeg', 'audio/wav', 'video/mp4', 'video/webm'
    ],
    
    # GraphRAG settings
    enable_graphrag=True,                 # Enable full GraphRAG
    vector_store_type="faiss",            # Vector store backend
    embedding_model="sentence-transformers/all-mpnet-base-v2",  # Better embeddings
    chunk_size=1500,                      # Larger chunks
    chunk_overlap=300,                    # More overlap
    
    # Performance settings
    max_parallel_processing=8,            # More parallel processing
    processing_timeout_minutes=60         # Longer timeout
)

processor = WebsiteGraphRAGProcessor(config=config)
```

### Content Processing Configuration

```python
# Multi-modal processor configuration
multimodal_config = {
    # Text processing
    'max_text_length': 200000,           # Process very long documents
    'chunk_size': 2000,                  # Larger chunks
    'chunk_overlap': 400,                # More overlap
    
    # Media processing
    'transcription_model': 'large',      # Best Whisper model
    'max_media_duration': 7200,          # 2 hours max
    'video_frame_interval': 15,          # Extract frames every 15 seconds
    
    # Embeddings
    'embedding_model': 'sentence-transformers/all-mpnet-base-v2',
    'batch_embedding_size': 16,          # Smaller batches for large model
    
    # Quality control
    'min_text_length': 100,              # Higher minimum length
    'confidence_threshold': 0.8          # Higher confidence threshold
}

processor = MultiModalContentProcessor(config=multimodal_config)
```

## Error Handling and Troubleshooting

### Common Issues and Solutions

```python
import logging

# Enable detailed logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def robust_website_processing(url):
    """Robust website processing with error handling"""
    
    try:
        # Attempt processing with retries
        for attempt in range(3):
            try:
                system = await processor.process_website(url)
                logger.info(f"Successfully processed {url} on attempt {attempt + 1}")
                return system
                
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
                if attempt == 2:  # Last attempt
                    raise
                await asyncio.sleep(5)  # Wait before retry
                
    except ValueError as e:
        logger.error(f"Invalid URL {url}: {e}")
        return None
        
    except RuntimeError as e:
        logger.error(f"Processing failed for {url}: {e}")
        
        # Try with reduced configuration
        try:
            logger.info(f"Retrying {url} with minimal configuration...")
            minimal_config = WebsiteProcessingConfig(
                archive_services=[],      # No external archiving
                crawl_depth=1,           # Shallow crawl
                include_media=False,     # No media processing
                enable_graphrag=False    # Basic vector search only
            )
            
            minimal_processor = WebsiteGraphRAGProcessor(config=minimal_config)
            system = await minimal_processor.process_website(url)
            logger.info(f"Successfully processed {url} with minimal configuration")
            return system
            
        except Exception as fallback_error:
            logger.error(f"Fallback processing also failed for {url}: {fallback_error}")
            return None

# Test robust processing
test_urls = [
    "https://example.com",           # Valid URL
    "https://nonexistent-site.com",  # Non-existent site
    "invalid-url"                    # Invalid URL format
]

for url in test_urls:
    result = asyncio.run(robust_website_processing(url))
    if result:
        print(f"✓ Successfully processed: {url}")
    else:
        print(f"✗ Failed to process: {url}")
```

## Performance Optimization Tips

### 1. Optimize for Large Websites

```python
# Configuration for processing large websites efficiently
large_site_config = WebsiteProcessingConfig(
    crawl_depth=2,                    # Limit depth
    max_file_size_mb=100,            # Skip very large files
    include_media=False,             # Skip media for speed
    max_parallel_processing=8,        # Use all CPU cores
    processing_timeout_minutes=120,   # Longer timeout
    
    # Use faster but less accurate models
    embedding_model="sentence-transformers/all-MiniLM-L6-v2",
    chunk_size=500,                  # Smaller chunks process faster
)
```

### 2. Memory Management

```python
# Process websites in batches to manage memory
async def process_websites_in_batches(urls, batch_size=3):
    results = []
    
    for i in range(0, len(urls), batch_size):
        batch_urls = urls[i:i + batch_size]
        
        print(f"Processing batch {i//batch_size + 1}: {batch_urls}")
        
        batch_results = await processor.process_multiple_websites(batch_urls)
        results.extend(batch_results)
        
        # Force garbage collection between batches
        import gc
        gc.collect()
        
        print(f"Completed batch {i//batch_size + 1}")
    
    return results
```

### 3. Caching and Persistence

```python
import pickle
import os

# Cache processed systems to avoid reprocessing
def save_graphrag_system(system, cache_dir="./graphrag_cache"):
    """Save processed GraphRAG system to disk"""
    os.makedirs(cache_dir, exist_ok=True)
    
    # Create filename from URL
    filename = system.url.replace("://", "_").replace("/", "_") + ".pkl"
    filepath = os.path.join(cache_dir, filename)
    
    with open(filepath, 'wb') as f:
        pickle.dump(system, f)
    
    print(f"Saved GraphRAG system to {filepath}")
    return filepath

def load_graphrag_system(url, cache_dir="./graphrag_cache"):
    """Load processed GraphRAG system from disk"""
    filename = url.replace("://", "_").replace("/", "_") + ".pkl"
    filepath = os.path.join(cache_dir, filename)
    
    if os.path.exists(filepath):
        with open(filepath, 'rb') as f:
            system = pickle.load(f)
        print(f"Loaded cached GraphRAG system for {url}")
        return system
    
    return None

# Use caching in processing workflow
async def process_with_caching(url):
    # Try to load from cache first
    cached_system = load_graphrag_system(url)
    if cached_system:
        return cached_system
    
    # Process if not cached
    system = await processor.process_website(url)
    
    # Save to cache
    save_graphrag_system(system)
    
    return system
```

This tutorial provides comprehensive examples of using the GraphRAG website processing system. The system can handle complete workflows from website archiving through searchable knowledge systems, with robust error handling and performance optimization.