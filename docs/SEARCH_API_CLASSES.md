# Search API Classes - Installation, Configuration, and Queue Management

## Overview

All search API integrations now include dedicated API classes with three key methods:
- `_install()` - Verify dependencies and provide installation instructions
- `_config(**kwargs)` - Configure API settings
- `_queue(operation, **params)` - Queue operations for batch processing

## Available API Classes

1. **BraveSearchAPI** - Brave Search integration
2. **GoogleSearchAPI** - Google Custom Search (coming soon)
3. **GitHubSearchAPI** - GitHub API search (coming soon) 
4. **HuggingFaceSearchAPI** - HuggingFace Hub (coming soon)
5. **OpenVerseSearchAPI** - OpenVerse Creative Commons media
6. **SerpStackSearchAPI** - SerpStack multi-engine search

## Usage Examples

### Brave Search API

```python
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.brave_search import BraveSearchAPI

# Initialize
api = BraveSearchAPI(api_key="your_api_key")
# Or use environment variable: BRAVE_API_KEY

# Check installation status
install_status = api._install()
print(install_status)
# Output:
# {
#     "status": "success",
#     "dependencies": {
#         "aiohttp": {"installed": True, "required": True, ...}
#     },
#     "environment_variables": {
#         "BRAVE_API_KEY": {"set": True, "required": True, ...}
#     },
#     "ready": True
# }

# Configure settings
config = api._config(
    timeout=60,
    max_count=15,
    default_lang="en",
    default_country="US"
)

# Queue operations
api._queue("search", query="machine learning", count=10)
api._queue("search_news", query="AI research", count=5)
api._queue("search_images", query="neural networks", count=20)

# Check queue status
status = api.get_queue_status()
print(f"Queued operations: {status['queue_length']}")

# Clear queue
api.clear_queue()
```

### OpenVerse Search API

```python
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.openverse_search import OpenVerseSearchAPI

# Initialize
api = OpenVerseSearchAPI(api_key="your_api_key")  # Optional
# Or use environment variable: OPENVERSE_API_KEY

# Verify installation
install_info = api._install()
if install_info['status'] != 'success':
    print("Missing dependencies:")
    for dep, info in install_info['dependencies'].items():
        if not info['installed']:
            print(f"  - {dep}: {info['install_command']}")

# Configure
api._config(
    max_results=100,
    timeout=30,
    default_license_type="cc0"  # Public domain only
)

# Queue searches
api._queue("search_images", query="nature", page_size=20, license_type="cc0")
api._queue("search_audio", query="music", page_size=10, source="jamendo")

# Process queue (custom implementation)
for item in api.queue:
    print(f"Process: {item['operation']} with {item['params']}")
```

### SerpStack Search API

```python
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.serpstack_search import SerpStackSearchAPI

# Initialize
api = SerpStackSearchAPI(api_key="your_api_key")
# Or use environment variable: SERPSTACK_API_KEY

# Check ready status
install_info = api._install()
if not install_info.get('ready'):
    print("Setup required:")
    for step, instruction in install_info['instructions'].items():
        print(f"  {step}. {instruction}")

# Configure
api._config(
    default_engine="google",
    max_results=100,
    timeout=30
)

# Queue multiple engine searches
api._queue("search", query="python tutorials", engine="google", num=10)
api._queue("search", query="python tutorials", engine="bing", num=10)
api._queue("search", query="python tutorials", engine="yahoo", num=10)

# Export queue for batch processing
queue_data = api.get_queue_status()
print(f"Total operations to process: {queue_data['operations_pending']}")
```

## Method Details

### _install()

Verifies dependencies and provides installation instructions.

**Returns:**
```python
{
    "status": "success" | "incomplete",
    "dependencies": {
        "package_name": {
            "installed": bool,
            "required": bool,
            "install_command": str
        }
    },
    "environment_variables": {
        "VAR_NAME": {
            "set": bool,
            "required": bool,
            "description": str
        }
    },
    "instructions": {
        "1": "First step...",
        "2": "Second step...",
        "3": "Third step..."
    },
    "ready": bool  # All dependencies met
}
```

### _config(**kwargs)

Configures API settings with validation.

**Parameters:** API-specific configuration options

**Returns:**
```python
{
    "status": "success",
    "configuration": {
        "setting1": value1,
        "setting2": value2,
        ...
    },
    "api_key_set": bool,
    "valid_config_keys": [...],
    "example": {...}
}
```

### _queue(operation, **params)

Queues operations for batch processing.

**Parameters:**
- `operation` (str): Operation type (e.g., "search", "search_images")
- `**params`: Operation-specific parameters

**Returns:**
```python
{
    "status": "success",
    "queue_item": {
        "id": int,
        "operation": str,
        "params": {...},
        "queued_at": str,
        "status": "queued"
    },
    "queue_length": int,
    "message": str
}
```

## Input Validation

All search functions now include comprehensive input validation:

```python
import asyncio
from ipfs_datasets_py.mcp_server.tools.web_archive_tools.brave_search import search_brave

async def example():
    # Invalid count - will return detailed error
    result = await search_brave(query="test", count=25)
    print(result)
    # Output:
    # {
    #     "status": "error",
    #     "error": "Count must be between 1 and 20",
    #     "validation": {
    #         "count": "Must be integer between 1 and 20"
    #     },
    #     "help": "Set count parameter between 1 and 20"
    # }

asyncio.run(example())
```

## LLM-Friendly Error Messages

All functions provide detailed error messages for language models:

```python
{
    "status": "error",
    "error": "Human-readable error message",
    "validation": {
        "parameter_name": "Validation rule description"
    },
    "help": "Specific guidance on how to fix the error"
}
```

## Environment Variables

### Required
- `BRAVE_API_KEY` - Brave Search API key
- `SERPSTACK_API_KEY` - SerpStack API key

### Optional
- `GOOGLE_API_KEY`, `GOOGLE_CSE_ID` - Google Custom Search
- `GITHUB_TOKEN` - GitHub API (increases rate limits)
- `HF_TOKEN` - HuggingFace Hub (for private data)
- `OPENVERSE_API_KEY` - OpenVerse (increases rate limits)

## New Search APIs

### OpenVerse API

Search Creative Commons licensed media:

```python
from ipfs_datasets_py.mcp_server.tools.web_archive_tools import (
    search_openverse_images,
    search_openverse_audio,
    batch_search_openverse
)

# Search CC images
result = await search_openverse_images(
    query="nature photography",
    license_type="cc0",  # Public domain
    page_size=20
)

# Search CC audio
result = await search_openverse_audio(
    query="classical music",
    source="jamendo",
    page_size=10
)

# Batch search
result = await batch_search_openverse(
    queries=["nature", "technology", "art"],
    search_type="images"
)
```

### SerpStack API

Multi-engine search results:

```python
from ipfs_datasets_py.mcp_server.tools.web_archive_tools import (
    search_serpstack,
    search_serpstack_images,
    batch_search_serpstack
)

# Search with Google
result = await search_serpstack(
    query="machine learning",
    engine="google",
    num=10,
    location="United States"
)

# Search with Bing
result = await search_serpstack(
    query="deep learning",
    engine="bing",
    num=10
)

# Batch search across engines
queries = ["python", "javascript", "rust"]
result = await batch_search_serpstack(
    queries=queries,
    engine="google",
    num=5
)
```

## Complete Example

```python
import asyncio
from ipfs_datasets_py.mcp_server.tools.web_archive_tools import (
    BraveSearchAPI,
    OpenVerseSearchAPI,
    SerpStackSearchAPI
)

async def complete_workflow():
    # Initialize APIs
    brave = BraveSearchAPI()
    openverse = OpenVerseSearchAPI()
    serpstack = SerpStackSearchAPI()
    
    # Check installations
    print("Checking installations...")
    for api, name in [(brave, "Brave"), (openverse, "OpenVerse"), (serpstack, "SerpStack")]:
        status = api._install()
        print(f"{name}: {'✓ Ready' if status.get('ready') else '⚠ Setup needed'}")
    
    # Configure all APIs
    brave._config(timeout=60, max_count=15)
    openverse._config(max_results=50)
    serpstack._config(default_engine="google")
    
    # Queue operations
    brave._queue("search", query="AI datasets", count=10)
    openverse._queue("search_images", query="data visualization", page_size=20)
    serpstack._queue("search", query="open datasets", engine="google", num=10)
    
    # Check queue status
    print(f"\nBrave queue: {brave.get_queue_status()['queue_length']} operations")
    print(f"OpenVerse queue: {openverse.get_queue_status()['queue_length']} operations")
    print(f"SerpStack queue: {serpstack.get_queue_status()['queue_length']} operations")

asyncio.run(complete_workflow())
```

## Benefits for Language Models

1. **Installation Verification**: `_install()` provides step-by-step setup instructions
2. **Configuration Validation**: `_config()` validates settings with examples
3. **Queue Management**: `_queue()` enables batch operation planning
4. **Detailed Errors**: Every error includes validation rules and help text
5. **Type Safety**: All parameters include type hints and validation
6. **Self-Documenting**: Classes return configuration examples and valid options

## Testing

Run the test suite:

```bash
cd /home/runner/work/ipfs_datasets_py/ipfs_datasets_py
python tests/test_search_api_classes.py
```

All tests should pass with output showing successful initialization, configuration, and queue management for each API class.
