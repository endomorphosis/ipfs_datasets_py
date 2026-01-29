# ipfs_kit_py Integration Guide

## Overview

`ipfs_kit_py` provides comprehensive IPFS operations and filesystem functionality for ipfs_datasets_py. This guide covers how ipfs_datasets_py integrates with and utilizes ipfs_kit_py for decentralized storage and content addressing.

## Key Features

### 1. Content-Addressed Storage
- Add files and directories to IPFS
- Retrieve content by CID (Content Identifier)
- Pin content for persistence
- Unpin content when no longer needed

### 2. IPFS Operations
- Direct IPFS daemon communication
- HTTP gateway access
- Pinning services integration
- Multi-hash support

### 3. CAR File Handling
- Create CAR (Content Addressable aRchive) files
- Extract data from CAR files
- Stream large CAR files
- CAR v1 and v2 support

### 4. IPLD Operations
- Navigate IPLD data structures
- Create and manipulate DAGs
- Codec support (dag-pb, dag-cbor, dag-json)
- Path resolution

## Installation

### Automatic Installation (Recommended)

ipfs_kit_py is automatically installed as a dependency:

```bash
# Install ipfs_datasets_py (includes ipfs_kit_py)
pip install -e .
```

### Git Submodule (Development)

```bash
# Initialize and update submodule
git submodule update --init --remote ipfs_kit_py

# Submodule is tracked on main branch
cd ipfs_kit_py
git checkout main
git pull origin main
```

### Manual Installation

```bash
# Clone and install separately
git clone https://github.com/endomorphosis/ipfs_kit_py.git
cd ipfs_kit_py
pip install -e .
```

## Branch Update (Important)

**⚠️ Changed from `known_good` to `main` branch**

All installations now use the `main` branch instead of the deprecated `known_good` branch:

```python
# Old (deprecated)
'ipfs_kit_py @ git+https://github.com/endomorphosis/ipfs_kit_py.git@known_good'

# New (current)
'ipfs_kit_py @ git+https://github.com/endomorphosis/ipfs_kit_py.git@main'
```

To update existing installations:

```bash
git submodule update --remote ipfs_kit_py
cd ipfs_kit_py
git checkout main
git pull origin main
```

## Basic Usage

### 1. Adding Content to IPFS

```python
from ipfs_datasets_py.ipfs_kit_integration import IPFSKit

# Initialize
kit = IPFSKit()

# Add a file
cid = kit.add_file("document.pdf")
print(f"Added file with CID: {cid}")

# Add a directory
dir_cid = kit.add_directory("my_dataset/")
print(f"Added directory with CID: {dir_cid}")

# Add from bytes
data = b"Hello, IPFS!"
data_cid = kit.add_bytes(data)
print(f"Added data with CID: {data_cid}")
```

### 2. Retrieving Content

```python
from ipfs_datasets_py.ipfs_kit_integration import IPFSKit

kit = IPFSKit()

# Get content by CID
cid = "QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG"
content = kit.get_content(cid)

# Save to file
kit.get_file(cid, output_path="downloaded_file.pdf")

# Get as bytes
data = kit.get_bytes(cid)

# Get directory
kit.get_directory(cid, output_dir="downloaded_dataset/")
```

### 3. Pinning Operations

```python
from ipfs_datasets_py.ipfs_kit_integration import IPFSKit

kit = IPFSKit()

# Pin content (keep it persistent)
cid = "QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG"
kit.pin(cid)

# Check if pinned
is_pinned = kit.is_pinned(cid)
print(f"Content pinned: {is_pinned}")

# Unpin when no longer needed
kit.unpin(cid)

# List all pins
pins = kit.list_pins()
for pin_cid in pins:
    print(f"Pinned: {pin_cid}")
```

### 4. CAR File Operations

```python
from ipfs_datasets_py.ipfs_kit_integration import IPFSKit

kit = IPFSKit()

# Create CAR file from directory
car_path = kit.create_car(
    source_path="my_dataset/",
    output_path="my_dataset.car"
)

# Extract CAR file
kit.extract_car(
    car_path="my_dataset.car",
    output_dir="extracted_dataset/"
)

# Get CID from CAR file
root_cid = kit.get_car_root_cid("my_dataset.car")
print(f"CAR root CID: {root_cid}")
```

## Integration Points in ipfs_datasets_py

### 1. Dataset Storage

Store datasets on IPFS:

```python
from ipfs_datasets_py import DatasetManager

manager = DatasetManager(storage="ipfs")

# Save dataset to IPFS
cid = manager.save_dataset(
    dataset=my_dataset,
    format="parquet"
)
print(f"Dataset saved to IPFS: {cid}")

# Load dataset from IPFS
loaded_dataset = manager.load_dataset(cid)
```

### 2. Document Processing

Store processed documents:

```python
from ipfs_datasets_py.pdf_processing import PDFProcessor

processor = PDFProcessor(storage_backend="ipfs")

# Process and store on IPFS
result = processor.process_document(
    pdf_path="document.pdf",
    store_on_ipfs=True
)
print(f"Processed document CID: {result['ipfs_cid']}")
```

### 3. Knowledge Graphs

Store knowledge graphs:

```python
from ipfs_datasets_py.knowledge_graphs import KnowledgeGraphExtractor

extractor = KnowledgeGraphExtractor()

# Extract and store graph
graph = extractor.extract_from_text(text)
cid = graph.save_to_ipfs()
print(f"Knowledge graph CID: {cid}")

# Load graph from IPFS
loaded_graph = extractor.load_from_ipfs(cid)
```

### 4. Vector Embeddings

Store embeddings on IPFS:

```python
from ipfs_datasets_py.embeddings import EmbeddingManager

manager = EmbeddingManager(storage="ipfs")

# Store embeddings
cid = manager.store_embeddings(
    embeddings=embedding_vectors,
    metadata=metadata_dict
)

# Retrieve embeddings
embeddings = manager.load_embeddings(cid)
```

### 5. Web Archives

Store web scraping results:

```python
from ipfs_datasets_py.web_archiving import WebArchiveProcessor

processor = WebArchiveProcessor()

# Scrape and store on IPFS
result = processor.scrape_url(
    url="https://example.com",
    store_on_ipfs=True
)
print(f"Web archive CID: {result['ipfs_cid']}")
```

## Advanced Usage

### 1. Custom IPFS Configuration

```python
from ipfs_datasets_py.ipfs_kit_integration import IPFSKit

# Connect to custom IPFS daemon
kit = IPFSKit(
    api_url="/ip4/127.0.0.1/tcp/5001",  # Custom API endpoint
    gateway_url="http://localhost:8080",  # Custom gateway
    timeout=60  # Connection timeout
)
```

### 2. Pinning Services Integration

```python
from ipfs_datasets_py.ipfs_kit_integration import IPFSKit

kit = IPFSKit()

# Add pinning service
kit.add_pinning_service(
    service_name="pinata",
    api_key="your_api_key",
    api_secret="your_api_secret"
)

# Pin to remote service
kit.remote_pin(
    cid="QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG",
    service="pinata",
    name="my_important_data"
)
```

### 3. Large File Handling

```python
from ipfs_datasets_py.ipfs_kit_integration import IPFSKit

kit = IPFSKit()

# Stream large file
with kit.stream_add("large_file.bin") as stream:
    for chunk_cid in stream:
        print(f"Added chunk: {chunk_cid}")

# Stream download
with kit.stream_get(cid, "output.bin") as stream:
    for chunk in stream:
        # Process chunk
        pass
```

### 4. IPLD Path Resolution

```python
from ipfs_datasets_py.ipfs_kit_integration import IPFSKit

kit = IPFSKit()

# Navigate IPLD structure
cid = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"

# Resolve path
content = kit.resolve_path(f"{cid}/path/to/data")

# Get links
links = kit.get_links(cid)
for link in links:
    print(f"Link: {link['Name']} -> {link['Hash']}")
```

### 5. Content Verification

```python
from ipfs_datasets_py.ipfs_kit_integration import IPFSKit

kit = IPFSKit()

# Verify content matches CID
is_valid = kit.verify_content(
    cid="QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG",
    content=file_content
)
print(f"Content valid: {is_valid}")

# Get content statistics
stats = kit.get_stats(cid)
print(f"Size: {stats['CumulativeSize']}")
print(f"Blocks: {stats['NumBlocks']}")
```

## Configuration

### Environment Variables

```bash
# IPFS daemon API endpoint
export IPFS_API_URL="/ip4/127.0.0.1/tcp/5001"

# IPFS HTTP gateway
export IPFS_GATEWAY_URL="http://localhost:8080"

# Integration mode
export IPFS_KIT_INTEGRATION="direct"  # or "mcp"

# MCP server URL (if using MCP mode)
export IPFS_KIT_MCP_URL="http://localhost:5001"
```

### Programmatic Configuration

```python
from ipfs_datasets_py.ipfs_kit_integration import configure_ipfs_kit

# Configure globally
configure_ipfs_kit(
    api_url="/ip4/127.0.0.1/tcp/5001",
    gateway_url="http://localhost:8080",
    integration_mode="direct",
    timeout=60,
    retry_attempts=3
)
```

## Integration Modes

### Direct Mode (Default)

Direct communication with IPFS daemon:

```python
# Set via environment
export IPFS_KIT_INTEGRATION=direct

# Or programmatically
kit = IPFSKit(integration_mode="direct")
```

### MCP Mode

Communication via MCP server:

```python
# Set via environment
export IPFS_KIT_INTEGRATION=mcp
export IPFS_KIT_MCP_URL=http://localhost:5001

# Or programmatically
kit = IPFSKit(
    integration_mode="mcp",
    mcp_url="http://localhost:5001"
)
```

## Error Handling

### Common Issues

#### 1. IPFS Daemon Not Running

```python
from ipfs_datasets_py.ipfs_kit_integration import IPFSKit, IPFSConnectionError

try:
    kit = IPFSKit()
    cid = kit.add_file("file.txt")
except IPFSConnectionError as e:
    print("IPFS daemon not running. Start with: ipfs daemon")
```

#### 2. CID Not Found

```python
from ipfs_datasets_py.ipfs_kit_integration import IPFSKit, ContentNotFoundError

try:
    kit = IPFSKit()
    content = kit.get_content("invalid_cid")
except ContentNotFoundError as e:
    print(f"Content not found: {e}")
```

#### 3. Timeout Issues

```python
from ipfs_datasets_py.ipfs_kit_integration import IPFSKit

# Increase timeout for large files
kit = IPFSKit(timeout=300)  # 5 minutes

try:
    cid = kit.add_file("large_file.bin")
except TimeoutError:
    print("Operation timed out. File too large or network slow.")
```

## Performance Optimization

### 1. Batch Operations

```python
from ipfs_datasets_py.ipfs_kit_integration import IPFSKit

kit = IPFSKit()

# Add multiple files at once
file_paths = ["file1.txt", "file2.txt", "file3.txt"]
cids = kit.add_files_batch(file_paths)

for path, cid in zip(file_paths, cids):
    print(f"{path} -> {cid}")
```

### 2. Parallel Transfers

```python
from ipfs_datasets_py.ipfs_kit_integration import IPFSKit
from concurrent.futures import ThreadPoolExecutor

kit = IPFSKit()

# Download multiple CIDs in parallel
cids = ["Qm...", "Qm...", "Qm..."]

with ThreadPoolExecutor(max_workers=5) as executor:
    futures = [executor.submit(kit.get_file, cid, f"file_{i}.dat") 
               for i, cid in enumerate(cids)]
    
    for future in futures:
        future.result()  # Wait for completion
```

### 3. Caching

```python
from ipfs_datasets_py.ipfs_kit_integration import IPFSKit

kit = IPFSKit(enable_cache=True)

# First access - fetches from IPFS
content1 = kit.get_content(cid)

# Second access - returns from cache
content2 = kit.get_content(cid)  # Much faster
```

## Testing

### Unit Tests

```python
import pytest
from ipfs_datasets_py.ipfs_kit_integration import IPFSKit

@pytest.fixture
def ipfs_kit():
    return IPFSKit()

def test_add_and_get(ipfs_kit, tmp_path):
    # Create test file
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello, IPFS!")
    
    # Add to IPFS
    cid = ipfs_kit.add_file(str(test_file))
    assert cid.startswith("Qm") or cid.startswith("bafy")
    
    # Retrieve content
    content = ipfs_kit.get_bytes(cid)
    assert content == b"Hello, IPFS!"
```

### Integration Tests

```python
def test_dataset_ipfs_roundtrip():
    from ipfs_datasets_py import DatasetManager
    
    manager = DatasetManager(storage="ipfs")
    
    # Create test dataset
    test_data = {"data": [1, 2, 3], "labels": [0, 1, 0]}
    
    # Save to IPFS
    cid = manager.save_dataset(test_data)
    
    # Load from IPFS
    loaded_data = manager.load_dataset(cid)
    
    # Verify
    assert loaded_data == test_data
```

## Docker Integration

### Dockerfile with IPFS

```dockerfile
FROM ipfs/go-ipfs:latest AS ipfs

FROM python:3.10-slim

# Copy IPFS binary
COPY --from=ipfs /usr/local/bin/ipfs /usr/local/bin/ipfs

# Install ipfs_datasets_py
RUN pip install ipfs-datasets-py

# Initialize IPFS
RUN ipfs init

# Start script
COPY start.sh /start.sh
RUN chmod +x /start.sh

CMD ["/start.sh"]
```

### Start Script

```bash
#!/bin/bash
# start.sh

# Start IPFS daemon in background
ipfs daemon &

# Wait for daemon to start
sleep 5

# Run your application
python your_app.py
```

## Troubleshooting

### Check IPFS Status

```python
from ipfs_datasets_py.ipfs_kit_integration import IPFSKit

kit = IPFSKit()

# Get IPFS version
version = kit.get_version()
print(f"IPFS Version: {version}")

# Check connectivity
is_connected = kit.is_connected()
print(f"Connected: {is_connected}")

# Get peer count
peer_count = kit.get_peer_count()
print(f"Connected to {peer_count} peers")
```

### Debug Mode

```python
import logging

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('ipfs_datasets_py.ipfs_kit_integration')
logger.setLevel(logging.DEBUG)

# Now see detailed IPFS operations
kit = IPFSKit()
```

## Best Practices

### 1. Always Pin Important Content

```python
kit = IPFSKit()

# Add and immediately pin
cid = kit.add_file("important.pdf")
kit.pin(cid)  # Ensures content persists
```

### 2. Use CAR Files for Large Datasets

```python
# For large datasets, use CAR format
kit.create_car("large_dataset/", "dataset.car")

# More efficient than individual files
```

### 3. Implement Retry Logic

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def reliable_add(file_path):
    kit = IPFSKit()
    return kit.add_file(file_path)
```

### 4. Clean Up Unused Pins

```python
# Regularly clean up old pins
kit = IPFSKit()
old_pins = kit.list_pins(older_than_days=30)

for cid in old_pins:
    if not kit.is_needed(cid):
        kit.unpin(cid)
```

## Additional Resources

- **ipfs_kit_py Repository:** https://github.com/endomorphosis/ipfs_kit_py
- **IPFS Documentation:** https://docs.ipfs.io/
- **IPLD Specification:** https://ipld.io/
- **CAR Format:** https://ipld.io/specs/transport/car/

## Summary

ipfs_kit_py integration provides:

✅ **Content-addressed storage** on IPFS  
✅ **Efficient CAR file** handling  
✅ **IPLD operations** and navigation  
✅ **Pinning management** for persistence  
✅ **Multiple integration modes** (direct, MCP)  
✅ **Production ready** with comprehensive testing  
✅ **Now using main branch** (updated from known_good)  

The integration enables seamless decentralized storage for all ipfs_datasets_py operations while maintaining simple APIs and graceful error handling.
