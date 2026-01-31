# Best Practices for IPFS Datasets Python

This guide covers best practices for using IPFS Datasets Python in development and production environments.

## 📋 Table of Contents

1. [Performance Best Practices](#performance-best-practices)
2. [Security Best Practices](#security-best-practices)
3. [Development Patterns](#development-patterns)
4. [Production Deployment](#production-deployment)
5. [Testing Strategies](#testing-strategies)
6. [Error Handling](#error-handling)
7. [Resource Management](#resource-management)
8. [Data Management](#data-management)

## ⚡ Performance Best Practices

### Use Hardware Acceleration

Enable hardware acceleration for significant performance improvements:

```python
from ipfs_datasets_py.dataset_manager import DatasetManager

# Enable acceleration (2-20x speedup)
manager = DatasetManager(use_accelerate=True)
```

### Batch Operations

Process data in batches rather than individually:

```python
# ❌ Don't do this
for item in dataset:
    result = process_single(item)
    
# ✅ Do this instead
batch_size = 100
for i in range(0, len(dataset), batch_size):
    batch = dataset[i:i+batch_size]
    results = process_batch(batch)
```

### Memory-Mapped Files

For large datasets, use memory mapping to avoid loading everything into RAM:

```python
from ipfs_datasets_py.streaming_data_loader import load_memory_mapped_vectors

# Efficient access to large vector datasets
vectors = load_memory_mapped_vectors(
    file_path="embeddings.bin",
    dimension=768,
    mode='r'
)
```

### Caching Strategies

Implement caching for frequently accessed data:

```python
from functools import lru_cache

@lru_cache(maxsize=1000)
def expensive_operation(key):
    # Expensive computation here
    return result
```

### Parallel Processing

Use parallel processing for CPU-bound operations:

```python
from concurrent.futures import ProcessPoolExecutor

with ProcessPoolExecutor(max_workers=4) as executor:
    results = list(executor.map(process_function, data_items))
```

## 🔒 Security Best Practices

### Never Commit Secrets

Use environment variables or secret management systems:

```python
import os

# ✅ Good - use environment variables
api_key = os.environ.get('OPENAI_API_KEY')

# ❌ Bad - hardcoded secrets
api_key = "sk-1234567890abcdef"  # Never do this!
```

### Validate Input

Always validate and sanitize user input:

```python
def process_file(filepath: str):
    # Validate filepath
    if not os.path.exists(filepath):
        raise ValueError(f"File not found: {filepath}")
    
    # Check file extension
    allowed_extensions = ['.pdf', '.txt', '.docx']
    if not any(filepath.endswith(ext) for ext in allowed_extensions):
        raise ValueError(f"Unsupported file type: {filepath}")
    
    # Process the file
    return process(filepath)
```

### Use Secure Connections

Always use HTTPS/TLS for network operations:

```python
# ✅ Good - secure connection
response = requests.get('https://api.example.com/data')

# ❌ Bad - insecure connection
response = requests.get('http://api.example.com/data')
```

### Implement Audit Logging

Track all operations for security and compliance:

```python
from ipfs_datasets_py.audit import AuditLogger

audit = AuditLogger()
audit.log_operation(
    user="user@example.com",
    operation="dataset_load",
    resource="squad",
    status="success"
)
```

## 💻 Development Patterns

### Use Type Hints

Type hints improve code quality and IDE support:

```python
from typing import List, Dict, Optional

def process_dataset(
    dataset_name: str,
    split: Optional[str] = None,
    max_items: Optional[int] = None
) -> Dict[str, List[str]]:
    """Process a dataset with optional filtering."""
    # Implementation
    return results
```

### Async/Await for I/O Operations

Use async operations for I/O-bound tasks:

```python
async def process_multiple_files(filepaths: List[str]) -> List[Result]:
    """Process multiple files concurrently."""
    tasks = [converter.convert(path) for path in filepaths]
    results = await asyncio.gather(*tasks)
    return results
```

### Result/Error Monads

Use Result types for explicit error handling:

```python
from ipfs_datasets_py.file_converter import FileConverter

converter = FileConverter()
result = await converter.convert('document.pdf')

if result.is_success():
    print(f"Success: {result.text}")
else:
    print(f"Error: {result.error}")
```

### Context Managers

Use context managers for resource management:

```python
from ipfs_datasets_py.database import DatabaseConnection

# ✅ Good - automatic cleanup
with DatabaseConnection() as db:
    results = db.query("SELECT * FROM data")

# ❌ Bad - manual cleanup required
db = DatabaseConnection()
results = db.query("SELECT * FROM data")
db.close()  # Easy to forget!
```

## 🚀 Production Deployment

### Use Configuration Management

Separate configuration from code:

```python
from ipfs_datasets_py.config import config

# Load configuration
cfg = config()

# Access settings
database_url = cfg.baseConfig['database']['url']
max_workers = cfg.baseConfig['processing']['max_workers']
```

### Implement Health Checks

Provide health check endpoints for monitoring:

```python
from ipfs_datasets_py.monitoring import HealthCheck

health = HealthCheck()

def health_check_endpoint():
    status = health.check_all()
    return {
        'status': 'healthy' if status.is_healthy() else 'unhealthy',
        'checks': status.details
    }
```

### Use Proper Logging

Implement structured logging with appropriate levels:

```python
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# Use appropriate log levels
logger.debug("Detailed debug information")
logger.info("Normal operation information")
logger.warning("Warning about potential issues")
logger.error("Error that needs attention")
logger.critical("Critical error requiring immediate action")
```

### Monitor Resource Usage

Track and alert on resource consumption:

```python
from ipfs_datasets_py.monitoring import ResourceMonitor

monitor = ResourceMonitor()
monitor.track_cpu_usage()
monitor.track_memory_usage()
monitor.set_alert_threshold(cpu_percent=80, memory_percent=85)
```

### Implement Graceful Shutdown

Handle shutdown signals properly:

```python
import signal
import sys

def signal_handler(sig, frame):
    logger.info("Shutting down gracefully...")
    # Clean up resources
    cleanup_resources()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
```

## 🧪 Testing Strategies

### Write Comprehensive Tests

Follow the testing pyramid:

```python
# Unit tests - Fast, isolated
def test_conversion_success():
    converter = FileConverter()
    result = converter.convert_sync('test.pdf')
    assert result.is_success()

# Integration tests - Components working together
def test_pdf_to_graphrag_pipeline():
    pdf = PDFProcessor()
    graph = GraphRAG()
    content = pdf.process('document.pdf')
    graph.add_document(content)
    assert graph.query("test") is not None

# E2E tests - Full workflows
def test_complete_pipeline():
    result = run_complete_pipeline()
    assert result.status == 'success'
```

### Use Test Fixtures

Reuse test setup with fixtures:

```python
import pytest

@pytest.fixture
def sample_dataset():
    """Provide a sample dataset for testing."""
    return load_test_dataset()

def test_with_fixture(sample_dataset):
    result = process(sample_dataset)
    assert result.is_valid()
```

### Mock External Dependencies

Use mocks for external services:

```python
from unittest.mock import Mock, patch

@patch('ipfs_datasets_py.ipfs_datasets')
def test_with_mock_ipfs(mock_ipfs):
    mock_ipfs.add_file.return_value = 'QmTest123'
    
    result = upload_to_ipfs('test.json')
    assert result == 'QmTest123'
```

## ⚠️ Error Handling

### Use Specific Exceptions

Catch specific exceptions rather than bare `except`:

```python
# ✅ Good - specific exception handling
try:
    result = risky_operation()
except ValueError as e:
    logger.error(f"Invalid value: {e}")
except FileNotFoundError as e:
    logger.error(f"File not found: {e}")
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    raise

# ❌ Bad - catches everything
try:
    result = risky_operation()
except:
    pass  # Silent failure!
```

### Provide Meaningful Error Messages

Include context in error messages:

```python
# ✅ Good - detailed error message
raise ValueError(
    f"Invalid dataset split '{split}'. "
    f"Available splits: {available_splits}"
)

# ❌ Bad - vague error message
raise ValueError("Invalid split")
```

### Use Custom Exceptions

Create custom exceptions for domain-specific errors:

```python
class DatasetNotFoundError(Exception):
    """Raised when a dataset cannot be found."""
    pass

class ConversionError(Exception):
    """Raised when file conversion fails."""
    pass

def load_dataset(name: str):
    if name not in available_datasets:
        raise DatasetNotFoundError(f"Dataset '{name}' not found")
```

## 💾 Resource Management

### Close Resources Properly

Always close files, connections, and other resources:

```python
# ✅ Good - using context manager
with open('data.txt', 'r') as f:
    content = f.read()

# ✅ Good - explicit cleanup
try:
    f = open('data.txt', 'r')
    content = f.read()
finally:
    f.close()
```

### Limit Concurrent Operations

Avoid overwhelming system resources:

```python
from concurrent.futures import ThreadPoolExecutor

# Limit concurrent threads
max_workers = min(32, os.cpu_count() + 4)
with ThreadPoolExecutor(max_workers=max_workers) as executor:
    results = executor.map(process_item, items)
```

### Monitor Memory Usage

Be aware of memory consumption:

```python
import psutil

def check_memory():
    memory = psutil.virtual_memory()
    if memory.percent > 85:
        logger.warning(f"High memory usage: {memory.percent}%")
        # Consider cleanup or throttling
```

## 📊 Data Management

### Use Appropriate Data Formats

Choose formats based on use case:

```python
# Parquet - Best for large datasets, columnar storage
manager.save_dataset(dataset, "output.parquet")

# JSONL - Good for streaming, human-readable
manager.save_dataset(dataset, "output.jsonl")

# CSV - Simple, widely compatible
manager.save_dataset(dataset, "output.csv")
```

### Implement Data Validation

Validate data quality:

```python
def validate_dataset(dataset):
    """Validate dataset quality."""
    # Check for required fields
    required_fields = ['id', 'text', 'label']
    for field in required_fields:
        if field not in dataset.column_names:
            raise ValueError(f"Missing required field: {field}")
    
    # Check for empty values
    if dataset.filter(lambda x: not x['text']).num_rows > 0:
        logger.warning("Dataset contains empty text fields")
    
    return True
```

### Version Your Data

Track data versions for reproducibility:

```python
metadata = {
    'version': '1.0.0',
    'created_at': datetime.now().isoformat(),
    'source': 'squad',
    'transformations': ['lowercase', 'tokenize'],
    'ipfs_cid': cid
}

with open('dataset_metadata.json', 'w') as f:
    json.dump(metadata, f)
```

## 📝 Documentation

### Document Your Code

Write clear docstrings:

```python
def process_document(
    filepath: str,
    extract_tables: bool = True,
    extract_images: bool = False
) -> ProcessedDocument:
    """
    Process a document and extract content.
    
    Args:
        filepath: Path to the document file
        extract_tables: Whether to extract tables
        extract_images: Whether to extract images
        
    Returns:
        ProcessedDocument with extracted content
        
    Raises:
        FileNotFoundError: If the file doesn't exist
        ConversionError: If conversion fails
    """
    # Implementation
```

### Keep README Updated

Maintain accurate documentation:
- Update when adding features
- Document breaking changes
- Provide migration guides
- Include examples

## 🔗 Related Guides

- **[Performance Optimization](guides/performance_optimization.md)** - Detailed optimization techniques
- **[Security & Governance](guides/security/security_governance.md)** - Security implementation
- **[Deployment Guide](deployment.md)** - Production deployment
- **[Configuration Guide](configuration.md)** - Configuration options

---

**Following these best practices will help you build reliable, performant, and maintainable applications with IPFS Datasets Python.**
