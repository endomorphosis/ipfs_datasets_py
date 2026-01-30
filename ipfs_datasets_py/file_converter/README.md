# File Converter Module

Unified file conversion for IPFS Datasets Python with gradual migration from external libraries to native implementation.

## Quick Start

```python
from ipfs_datasets_py.file_converter import FileConverter

# Initialize (auto-selects best available backend)
converter = FileConverter()

# Convert a file
result = await converter.convert('document.pdf')
print(result.text)
print(result.metadata)

# Or use synchronously
result = converter.convert_sync('document.pdf')
```

## Backends

### Auto (Recommended)
```python
converter = FileConverter()  # or FileConverter(backend='auto')
```
Automatically selects the best available backend in this order:
1. **MarkItDown** - Fast, stable, broad format support
2. **Omni** - Rich metadata, comprehensive features
3. **Native** - Basic formats, always available

### MarkItDown (Phase 1 - External)
```python
converter = FileConverter(backend='markitdown')
```
- **Best for:** Fast conversion, web URLs, async operations
- **Formats:** 20+ including PDF, DOCX, XLSX, HTML, images
- **Install:** `pip install ipfs-datasets-py[file_conversion]`

### Omni (Phase 1 - External)
```python
converter = FileConverter(backend='omni')
```
- **Best for:** Rich metadata, batch processing, training data
- **Formats:** 25 formats across text, image, audio, video, application
- **Install:** Submodule (already available)

### Native (Phase 2+ - Internal)
```python
converter = FileConverter(backend='native')
```
- **Best for:** No external dependencies
- **Formats:** Currently txt, md, json, csv, html, xml (expanding)
- **Install:** Always available

## Usage Examples

### Basic Conversion
```python
converter = FileConverter()
result = await converter.convert('research.pdf')

if result.success:
    print(f"Converted {len(result.text)} characters")
    print(f"Backend: {result.backend}")
else:
    print(f"Error: {result.error}")
```

### Batch Processing
```python
from pathlib import Path

converter = FileConverter()
files = list(Path('documents/').rglob('*.pdf'))

results = await converter.convert_batch(files, max_concurrent=5)
successful = [r for r in results if r.success]
print(f"Converted {len(successful)}/{len(files)} files")
```

### GraphRAG Integration
```python
from ipfs_datasets_py.file_converter import FileConverter
from ipfs_datasets_py.rag import GraphRAG

converter = FileConverter()
graph = GraphRAG()

# Convert and add to knowledge graph
result = await converter.convert('paper.pdf')
if result.success:
    await graph.add_document(result.text, metadata=result.metadata)
```

### Check Supported Formats
```python
converter = FileConverter(backend='markitdown')
formats = converter.get_supported_formats()
print(f"Supports: {', '.join(formats)}")

info = converter.get_backend_info()
print(f"Backend: {info['name']}, Formats: {info['supported_formats']}")
```

## Installation

### Minimal (Native backend only)
```bash
pip install ipfs-datasets-py
```

### With MarkItDown (Recommended)
```bash
pip install ipfs-datasets-py[file_conversion]
```

### Full Support (All backends)
```bash
pip install ipfs-datasets-py[file_conversion_full]
```

## Migration Strategy

### Phase 1 (Current): Import & Wrap
- Use external libraries (MarkItDown, omni_converter_mk2)
- Simple wrapper API
- Immediate functionality

### Phase 2 (Month 2-4): Selective Reimplementation
- Port best features natively
- Async file converter
- Format detection
- Metadata extraction
- Batch processing

### Phase 3 (Month 5-6): Full Native (Optional)
- Complete native implementation
- Remove external dependencies
- Optimized for ipfs_datasets_py

## API Reference

### FileConverter

```python
class FileConverter:
    def __init__(
        backend: Literal['auto', 'omni', 'markitdown', 'native'] = 'auto',
        **options
    )
    
    async def convert(
        file_path: Union[str, Path],
        **kwargs
    ) -> ConversionResult
    
    def convert_sync(
        file_path: Union[str, Path],
        **kwargs
    ) -> ConversionResult
    
    async def convert_batch(
        file_paths: List[Union[str, Path]],
        max_concurrent: int = 5,
        **kwargs
    ) -> List[ConversionResult]
    
    def get_supported_formats() -> List[str]
    
    def get_backend_info() -> dict
```

### ConversionResult

```python
@dataclass
class ConversionResult:
    text: str              # Extracted text content
    metadata: dict         # Additional metadata
    backend: str           # Backend that performed conversion
    success: bool          # Whether conversion succeeded
    error: Optional[str]   # Error message if failed
```

## Related Documentation

- [Integration Plan](../../docs/FILE_CONVERSION_INTEGRATION_PLAN.md) - Full migration strategy
- [Pros & Cons](../../docs/FILE_CONVERSION_PROS_CONS.md) - Backend comparison
- [Systems Analysis](../../docs/FILE_CONVERSION_SYSTEMS_ANALYSIS.md) - Detailed analysis
- [Merge Feasibility](../../docs/FILE_CONVERSION_MERGE_FEASIBILITY.md) - Why this approach

## Contributing

Adding new formats to native backend:

1. Add format handler in `backends/native_backend.py`
2. Add format to `get_supported_formats()`
3. Add tests in `tests/test_file_converter.py`
4. Update this README

See [INTEGRATION_PLAN.md](../../docs/FILE_CONVERSION_INTEGRATION_PLAN.md) for roadmap.
