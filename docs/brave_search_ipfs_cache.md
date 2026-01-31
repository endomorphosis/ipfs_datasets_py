# Brave Search IPFS Content-Addressed Cache

## Overview

The Brave Search client now supports distributed, content-addressed caching using IPFS/libp2p. This enables cache sharing across multiple nodes with cryptographic verification and deduplication.

## Architecture

### Hybrid Caching Strategy

```
Search Request
    ↓
[1] Check Local File Cache (fastest)
    ↓ Cache Miss
[2] Check IPFS Cache (distributed)
    ↓ Cache Miss
[3] Call Brave Search API
    ↓
[4] Store in Local Cache
    ↓
[5] Store in IPFS Cache (if enabled)
    ↓
Return Results
```

### Benefits

1. **Distributed Caching**: Share cache across multiple nodes
2. **Content Addressing**: Cryptographic verification via CIDs
3. **Deduplication**: Identical results automatically deduplicated
4. **Cost Savings**: Reduced API calls across your fleet
5. **Persistence**: IPFS cache survives local cache clears
6. **Peer Discovery**: Automatically discover cached results from peers

### Storage Model

**Local Cache:**
- Storage: Single JSON file on disk
- Key: SHA256 hash of query parameters
- Scope: Single machine
- Speed: Fastest (local filesystem)

**IPFS Cache:**
- Storage: Content-addressed in IPFS
- Key: IPFS CID (derived from content)
- Scope: Distributed network
- Speed: Fast (DHT lookup + local pin or network fetch)

## Configuration

### Enable IPFS Caching

```bash
# Enable IPFS cache
export BRAVE_SEARCH_IPFS_CACHE=1

# Set IPFS daemon connection (default: /ip4/127.0.0.1/tcp/5001)
export IPFS_HOST=/ip4/127.0.0.1/tcp/5001

# Configure TTL (default: 7 days = 604800 seconds)
export BRAVE_SEARCH_IPFS_TTL_S=604800

# Enable automatic pinning of cache entries (prevents GC)
export BRAVE_SEARCH_IPFS_PIN=1

# Custom CID index location (default: state/brave_ipfs_cache_index.json)
export BRAVE_SEARCH_IPFS_INDEX_PATH=/path/to/index.json
```

### Prerequisites

1. **IPFS Daemon**: Running IPFS daemon (kubo/go-ipfs)
   ```bash
   ipfs daemon
   ```

2. **Python Dependencies**: Install ipfshttpclient
   ```bash
   pip install ipfshttpclient
   ```

## Usage

### Python API

```python
from ipfs_datasets_py.web_archiving import BraveSearchClient

# Initialize client with IPFS caching enabled
# (requires BRAVE_SEARCH_IPFS_CACHE=1 environment variable)
client = BraveSearchClient(api_key="your-key")

# Search - automatically uses IPFS cache if available
results = client.search("machine learning", count=20)

# Get IPFS cache statistics
ipfs_stats = client.ipfs_cache_stats()
print(f"IPFS connected: {ipfs_stats['ipfs_connected']}")
print(f"CID index entries: {ipfs_stats['cid_index_entries']}")
print(f"IPFS peer ID: {ipfs_stats['ipfs_peer_id']}")

# Cache management
client.ipfs_cache_clear_index()  # Clear local CID index
client.ipfs_cache_gc()  # Garbage collect unpinned entries

# Pin management
client.ipfs_cache_pin("QmHash...")  # Pin important cache entry
client.ipfs_cache_unpin("QmHash...")  # Unpin cache entry
pins = client.ipfs_cache_list_pins()  # List all pins
```

### Direct IPFS Cache API

```python
from ipfs_datasets_py.web_archiving import BraveSearchIPFSCache

# Initialize IPFS cache
cache = BraveSearchIPFSCache()

if cache.is_available():
    # Store results in IPFS
    results = [{"title": "...", "url": "...", "description": "..."}]
    cid = cache.store(
        query="test query",
        results=results,
        count=10,
        offset=0,
        country="us",
        safesearch="moderate",
        metadata={"total": 100}
    )
    print(f"Stored in IPFS: {cid}")
    
    # Retrieve from IPFS
    cached = cache.retrieve(
        query="test query",
        count=10,
        offset=0,
        country="us",
        safesearch="moderate"
    )
    if cached:
        print(f"Cache hit! CID: {cached['cid']}")
        print(f"Results: {len(cached['results'])}")
        print(f"Cache age: {cached['cache_age_s']}s")
    
    # Get statistics
    stats = cache.stats()
    print(f"IPFS version: {stats['ipfs_version']}")
    print(f"Peer ID: {stats['ipfs_peer_id']}")
    print(f"Index entries: {stats['cid_index_entries']}")
    
    # Pin management
    cache.pin_entry(cid)
    cache.list_pins()
    cache.unpin_entry(cid)
    
    # Garbage collection
    result = cache.gc()
    print(f"Freed {result['freed_count']} items")
```

### Environment-Based Configuration

```python
import os

# Enable IPFS cache for this session
os.environ["BRAVE_SEARCH_IPFS_CACHE"] = "1"
os.environ["BRAVE_SEARCH_IPFS_PIN"] = "1"

from ipfs_datasets_py.web_archiving import BraveSearchClient

client = BraveSearchClient()
results = client.search("test")  # Uses IPFS cache
```

## How It Works

### Cache Storage

When you search with IPFS caching enabled:

1. **Query Normalization**: Query parameters are normalized into a canonical form
2. **CID Index Lookup**: Local index checked for matching query → CID mapping
3. **IPFS Retrieval**: If CID found, content retrieved from IPFS (local or network)
4. **Content Verification**: CID cryptographically verifies content integrity
5. **TTL Check**: Timestamp checked against configured TTL

### Cache Sharing

Cache entries are automatically shared across nodes:

1. **Node A** searches and caches result in IPFS → CID: `QmAbc123...`
2. **Node B** performs same search → checks local → checks IPFS
3. **Node B** discovers CID via DHT or direct connection to Node A
4. **Node B** retrieves content from IPFS network
5. **Node B** verifies content via CID and stores in local index

### Content Addressing

Each cache entry is identified by its IPFS CID (Content Identifier):

```json
{
  "query": "machine learning",
  "count": 10,
  "offset": 0,
  "country": "us",
  "safesearch": "moderate",
  "results": [...],
  "metadata": {...},
  "timestamp": 1706789123.456,
  "version": "v1"
}
```

This content is:
1. Serialized to JSON
2. Hashed with SHA-256
3. Stored in IPFS with CID (e.g., `QmHash...`)
4. CID maps query params → content

### Local CID Index

To avoid DHT lookups for every query, a local index maintains mappings:

```json
{
  "sha256_of_query_params": {
    "cid": "QmAbc123...",
    "timestamp": 1706789123.456,
    "query": "machine learning (truncated)",
    "result_count": 10
  }
}
```

## Cache Management

### View Cache Statistics

```python
client = BraveSearchClient()

# IPFS cache stats
ipfs_stats = client.ipfs_cache_stats()
print(f"Available: {ipfs_stats['available']}")
print(f"Connected: {ipfs_stats['ipfs_connected']}")
print(f"Version: {ipfs_stats['ipfs_version']}")
print(f"Peer ID: {ipfs_stats['ipfs_peer_id']}")
print(f"Index entries: {ipfs_stats['cid_index_entries']}")
print(f"TTL: {ipfs_stats['ttl_s']}s")
```

### Clear CID Index

```python
# Clear local CID index (doesn't remove IPFS data)
result = client.ipfs_cache_clear_index()
print(f"Cleared {result['cleared_entries']} entries")
```

### Garbage Collection

```python
# Remove unpinned IPFS cache entries
result = client.ipfs_cache_gc()
print(f"Freed {result['freed_count']} items")
```

### Pin Important Entries

```python
# Pin entries to prevent garbage collection
client.ipfs_cache_pin("QmHash...")

# List all pins
pins = client.ipfs_cache_list_pins()
for pin in pins['pins']:
    print(f"CID: {pin['cid']}, Type: {pin['type']}")

# Unpin when no longer needed
client.ipfs_cache_unpin("QmHash...")
```

## Performance Characteristics

### Cache Hit Latency

- **Local file cache**: ~1-5ms
- **IPFS local pin**: ~5-20ms
- **IPFS network fetch**: ~100-1000ms (depends on network)
- **API request**: ~200-2000ms (depends on API latency)

### Cache Size

- **Local file cache**: Limited by disk, typically MB-GB
- **IPFS cache**: Limited by IPFS repo size (configurable GB-TB)
- **Network**: Unlimited (distributed across peers)

### Bandwidth

- **Cache hit (local)**: No bandwidth
- **Cache hit (IPFS network)**: Only transfer cached entry (~1-10KB per entry)
- **Cache miss**: Full API bandwidth + caching overhead

## Deployment Scenarios

### Single Machine Development

```bash
# Start IPFS daemon
ipfs daemon &

# Enable IPFS caching
export BRAVE_SEARCH_IPFS_CACHE=1

# Use normally - benefits from persistence across runs
python your_script.py
```

### Multi-Node Fleet

**On each node:**
```bash
# Start IPFS daemon with libp2p networking
ipfs daemon &

# Connect nodes to each other
ipfs swarm connect /ip4/node1-ip/tcp/4001/p2p/Qm...
ipfs swarm connect /ip4/node2-ip/tcp/4001/p2p/Qm...

# Enable IPFS caching
export BRAVE_SEARCH_IPFS_CACHE=1
export BRAVE_SEARCH_IPFS_PIN=1  # Pin on first node that caches

# Run your application
python your_app.py
```

**Benefits:**
- First node to search caches result
- Other nodes retrieve from IPFS instead of API
- Automatic deduplication across fleet
- Reduced API costs

### Long-Term Archival

```bash
# Enable pinning for important queries
export BRAVE_SEARCH_IPFS_PIN=1

# Archive search results permanently
python -c "
from ipfs_datasets_py.web_archiving import BraveSearchClient
client = BraveSearchClient()

# These results will be pinned and archived
for topic in ['AI', 'quantum computing', 'CRISPR']:
    results = client.search(topic, count=20)
    print(f'Archived {len(results)} results for: {topic}')
"

# List archived searches
from ipfs_datasets_py.web_archiving import BraveSearchIPFSCache
cache = BraveSearchIPFSCache()
pins = cache.list_pins()
print(f"Total pinned entries: {pins['count']}")
```

## Troubleshooting

### IPFS Not Connected

**Symptom**: `ipfs_connected: false` in stats

**Solution**:
```bash
# Start IPFS daemon
ipfs daemon

# Or check if it's already running
ipfs id
```

### Cache Not Working

**Symptom**: All requests hit API despite caching enabled

**Check**:
```python
from ipfs_datasets_py.web_archiving import BraveSearchClient

client = BraveSearchClient()
stats = client.ipfs_cache_stats()

if not stats['available']:
    print("IPFS cache not available")
    print("Enable with: export BRAVE_SEARCH_IPFS_CACHE=1")

if not stats['ipfs_connected']:
    print("IPFS daemon not running")
    print("Start with: ipfs daemon")
```

### High Memory Usage

**Issue**: IPFS using too much memory

**Solution**:
```bash
# Configure IPFS memory limits in config
ipfs config Datastore.StorageMax "10GB"

# Reduce cache size
export BRAVE_SEARCH_IPFS_TTL_S=86400  # 1 day instead of 7

# Run garbage collection regularly
ipfs repo gc
```

### Slow Cache Retrieval

**Issue**: IPFS cache slower than expected

**Optimization**:
1. **Pre-warm cache**: Pin frequently used entries
2. **Local cluster**: Connect nodes via private network
3. **Selective pinning**: Only pin important queries
4. **TTL tuning**: Shorter TTL for less frequently used data

## Security Considerations

1. **Content Integrity**: CIDs cryptographically verify content
2. **No Authentication**: IPFS cache is public by default
3. **Privacy**: Queries visible to IPFS network (cache is public)
4. **Quota**: Set IPFS storage limits to prevent abuse

**For Private Caching**:
- Use IPFS private network
- Or stick with local file caching only

## Comparison: Local vs IPFS Cache

| Feature | Local File Cache | IPFS Cache |
|---------|-----------------|------------|
| Speed | Fastest (~1-5ms) | Fast (~5-1000ms) |
| Scope | Single machine | Distributed network |
| Persistence | Until file deleted | Until GC (or pinned forever) |
| Sharing | No | Yes (automatic) |
| Deduplication | Per machine | Network-wide |
| Verification | Hash-based | CID (cryptographic) |
| Storage Limit | Disk space | IPFS repo size |
| Network Required | No | Yes (for sharing) |

## Best Practices

1. **Hybrid Mode**: Keep both local and IPFS caching enabled
2. **Pin Important**: Pin frequently used or important queries
3. **Regular GC**: Run garbage collection to free space
4. **Monitor Stats**: Check cache statistics regularly
5. **TTL Tuning**: Adjust TTL based on your needs
6. **Network Config**: Configure IPFS for your network topology

## Related Documentation

- **Brave Search Client**: `docs/brave_search_client.md`
- **IPFS Integration**: IPFS documentation at ipfs.io
- **ipfshttpclient**: Python IPFS HTTP client library
