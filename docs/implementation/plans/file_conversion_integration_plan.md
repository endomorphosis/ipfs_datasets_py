# Gradual Integration Plan: File Conversion Systems

**Date:** January 30, 2026  
**Strategy:** Use both codebases as inspiration, import directly, gradually reimplement  
**Goal:** Native file conversion capabilities in ipfs_datasets_py

---

## 🎯 Strategy Overview

Instead of merging codebases or keeping them completely separate, we'll:

1. **Import Both Libraries** - Use them directly via imports (immediate value)
2. **Create Unified Wrapper** - Single API in ipfs_datasets_py that routes to best backend
3. **Gradual Reimplementation** - Reimplement features natively as needed
4. **Maintain Compatibility** - Keep working during migration

**Benefits:**
- ✅ Immediate functionality (use libraries now)
- ✅ Low risk (libraries are proven)
- ✅ Gradual migration (no big bang)
- ✅ Learn from best practices (both codebases)
- ✅ Native integration eventually

---

## 📊 Three-Phase Approach

### Phase 1: Import & Wrap (Week 1-2) 🟢 START HERE

**Goal:** Provide file conversion capability immediately using existing libraries.

**Tasks:**
1. Add both packages as optional dependencies
2. Create `ipfs_datasets_py.file_converter` module
3. Build wrapper that intelligently routes to best backend
4. Add usage examples
5. Test with GraphRAG integration

**Output:** Users can convert files immediately using stable libraries.

**Risk:** 🟢 Minimal - Just wrapping existing code

---

### Phase 2: Selective Reimplementation (Month 2-4) 🟡 INCREMENTAL

**Goal:** Reimplement the most valuable features natively.

**Priority Features to Reimplement:**

**High Priority (Month 2):**
1. **Async File Converter** - Port convert_to_txt's monadic pipeline
2. **Format Detection** - MIME type detection from both systems
3. **Basic Text Extraction** - Simple converters (txt, html, json)
4. **Error Handling** - Unified error handling from both

**Medium Priority (Month 3):**
5. **Metadata Extraction** - Port omni's rich metadata capability
6. **Batch Processing** - Async batch from convert_to_txt with omni's features
7. **Progress Tracking** - Combined best of both systems
8. **Resource Management** - Memory/CPU limits from omni

**Low Priority (Month 4):**
9. **Text Normalization** - omni's normalization features
10. **Security Validation** - omni's security checks
11. **Caching Layer** - Performance optimization
12. **Format-Specific Optimizations** - PDF, DOCX, etc.

**Output:** Core features implemented natively, reducing external dependencies.

**Risk:** 🟡 Medium - Each feature tested independently

---

### Phase 3: Full Native Implementation (Month 5-6) 🟡 OPTIONAL

**Goal:** Complete native implementation, deprecate external libraries.

**Tasks:**
1. Implement remaining format handlers
2. Advanced metadata extraction
3. Performance optimization
4. Remove optional dependencies
5. Full test coverage

**Output:** Fully native, optimized file conversion in ipfs_datasets_py.

**Risk:** 🟡 Medium - Requires comprehensive testing

**Note:** This phase is optional. We can maintain library imports indefinitely if they work well.

---

## 🏗️ Architecture

### Current Structure
```
ipfs_datasets_py/
├── multimedia/                      # Existing media processing
│   ├── omni_converter_mk2/         # Submodule (draft/inspiration)
│   ├── convert_to_txt_based_on_mime_type/  # Submodule (draft/inspiration)
│   ├── ffmpeg_wrapper.py
│   └── ytdlp_wrapper.py
```

### New Structure (Phase 1)
```
ipfs_datasets_py/
├── file_converter/                  # NEW: Unified conversion module
│   ├── __init__.py                 # Public API
│   ├── converter.py                # Main FileConverter class
│   ├── backends/                   # Backend adapters
│   │   ├── __init__.py
│   │   ├── omni_backend.py        # Adapter for omni_converter_mk2
│   │   ├── markitdown_backend.py  # Adapter for convert_to_txt
│   │   └── native_backend.py      # Native implementations (Phase 2+)
│   ├── utils.py                    # Shared utilities
│   ├── types.py                    # Type definitions
│   └── README.md                   # Usage documentation
├── multimedia/                      # Keep existing
│   ├── omni_converter_mk2/         # Used via import (Phase 1)
│   ├── convert_to_txt_based_on_mime_type/  # Used via import (Phase 1)
│   └── ...
```

### API Design (Public Interface)
```python
# Simple, clean API that won't change during migration
from ipfs_datasets_py.processors.file_converter import FileConverter

# Initialize with auto backend selection
converter = FileConverter()

# Or specify backend explicitly
converter = FileConverter(backend='omni')  # Rich metadata
converter = FileConverter(backend='markitdown')  # Fast async
converter = FileConverter(backend='native')  # Native (Phase 2+)

# Convert file (async)
result = await converter.convert('document.pdf')
print(result.text)
print(result.metadata)

# Batch convert (async)
results = await converter.convert_batch(['file1.pdf', 'file2.docx'])

# Sync wrapper for convenience
result_sync = converter.convert_sync('document.pdf')
```

---

## 📦 Dependency Management

### setup.py Updates

```python
# In setup.py extras_require section

extras_require={
    # Existing extras...
    
    # File conversion support (Phase 1)
    'file_conversion': [
        'markitdown>=0.1.0',          # Microsoft's converter
        'aiohttp>=3.8.0',              # Async HTTP
        'playwright>=1.40.0',          # Web content
    ],
    
    'file_conversion_full': [
        'markitdown>=0.1.0',
        'aiohttp>=3.8.0',
        'playwright>=1.40.0',
        # omni_converter_mk2 dependencies (selective)
        'pytesseract>=0.3.10',         # OCR for images
        'python-docx>=0.8.11',         # Word documents
        'openpyxl>=3.0.0',             # Excel
        'PyPDF2>=3.0.0',               # PDF processing
        'python-pptx>=0.6.21',         # PowerPoint
        'beautifulsoup4>=4.11.0',      # HTML parsing
    ],
    
    # All features
    'all': [
        # ... existing all deps ...
        'markitdown>=0.1.0',
        'aiohttp>=3.8.0',
    ],
}
```

### Installation

```bash
# Minimal file conversion (recommended)
pip install ipfs-datasets-py[file_conversion]

# Full file conversion support
pip install ipfs-datasets-py[file_conversion_full]

# Everything
pip install ipfs-datasets-py[all]
```

---

## 🔌 Phase 1 Implementation Details

### 1. Main Converter Class

**File:** `ipfs_datasets_py/file_converter/converter.py`

```python
"""
Unified file converter for ipfs_datasets_py.

Uses existing libraries initially, gradually migrating to native implementation.
"""

from pathlib import Path
from typing import Optional, Union, List, Literal
from dataclasses import dataclass
import asyncio

@dataclass
class ConversionResult:
    """Result of file conversion."""
    text: str
    metadata: dict
    backend: str
    success: bool
    error: Optional[str] = None

class FileConverter:
    """
    Unified file converter with pluggable backends.
    
    Phase 1: Uses omni_converter_mk2 and convert_to_txt_based_on_mime_type
    Phase 2+: Gradually adds native implementations
    
    Examples:
        # Auto-select backend
        converter = FileConverter()
        result = await converter.convert('document.pdf')
        
        # Specify backend
        converter = FileConverter(backend='markitdown')
        result = await converter.convert('file.docx')
        
        # Batch processing
        results = await converter.convert_batch(['f1.pdf', 'f2.docx'])
    """
    
    def __init__(
        self,
        backend: Literal['auto', 'omni', 'markitdown', 'native'] = 'auto',
        **options
    ):
        """
        Initialize converter.
        
        Args:
            backend: Which backend to use
                - 'auto': Choose best based on requirements
                - 'omni': Use omni_converter_mk2 (rich metadata)
                - 'markitdown': Use convert_to_txt (fast, async)
                - 'native': Use native implementation (Phase 2+)
            **options: Backend-specific options
        """
        self.backend_name = backend
        self.options = options
        self._backend = None
    
    def _get_backend(self):
        """Lazy-load backend on first use."""
        if self._backend is not None:
            return self._backend
            
        if self.backend_name == 'auto':
            # Try markitdown first (fast, stable)
            try:
                from .backends.markitdown_backend import MarkItDownBackend
                self._backend = MarkItDownBackend(**self.options)
                return self._backend
            except ImportError:
                pass
            
            # Fallback to omni
            try:
                from .backends.omni_backend import OmniBackend
                self._backend = OmniBackend(**self.options)
                return self._backend
            except ImportError:
                pass
            
            # Last resort: native (Phase 2+)
            from .backends.native_backend import NativeBackend
            self._backend = NativeBackend(**self.options)
            
        elif self.backend_name == 'omni':
            from .backends.omni_backend import OmniBackend
            self._backend = OmniBackend(**self.options)
            
        elif self.backend_name == 'markitdown':
            from .backends.markitdown_backend import MarkItDownBackend
            self._backend = MarkItDownBackend(**self.options)
            
        elif self.backend_name == 'native':
            from .backends.native_backend import NativeBackend
            self._backend = NativeBackend(**self.options)
            
        return self._backend
    
    async def convert(
        self,
        file_path: Union[str, Path],
        **kwargs
    ) -> ConversionResult:
        """
        Convert file to text asynchronously.
        
        Args:
            file_path: Path to file to convert
            **kwargs: Backend-specific options
            
        Returns:
            ConversionResult with text and metadata
        """
        backend = self._get_backend()
        return await backend.convert(file_path, **kwargs)
    
    def convert_sync(
        self,
        file_path: Union[str, Path],
        **kwargs
    ) -> ConversionResult:
        """
        Convert file to text synchronously.
        
        Convenience wrapper around async convert().
        """
        return asyncio.run(self.convert(file_path, **kwargs))
    
    async def convert_batch(
        self,
        file_paths: List[Union[str, Path]],
        max_concurrent: int = 5,
        **kwargs
    ) -> List[ConversionResult]:
        """
        Convert multiple files concurrently.
        
        Args:
            file_paths: List of files to convert
            max_concurrent: Maximum concurrent conversions
            **kwargs: Backend-specific options
            
        Returns:
            List of ConversionResults
        """
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def convert_with_semaphore(path):
            async with semaphore:
                return await self.convert(path, **kwargs)
        
        tasks = [convert_with_semaphore(p) for p in file_paths]
        return await asyncio.gather(*tasks, return_exceptions=True)
    
    def get_supported_formats(self) -> List[str]:
        """Get list of supported file formats."""
        backend = self._get_backend()
        return backend.get_supported_formats()
```

### 2. Backend Adapters

**File:** `ipfs_datasets_py/file_converter/backends/markitdown_backend.py`

```python
"""Adapter for convert_to_txt_based_on_mime_type using MarkItDown."""

from pathlib import Path
from typing import Union
from ..converter import ConversionResult

class MarkItDownBackend:
    """Backend using convert_to_txt_based_on_mime_type."""
    
    def __init__(self, **options):
        self.options = options
        self._converter = None
    
    def _get_converter(self):
        """Lazy-load converter."""
        if self._converter is None:
            try:
                # Try importing from submodule
                import sys
                sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'multimedia' / 'convert_to_txt_based_on_mime_type'))
                from converter_system.conversion_pipeline import file_converter
                self._converter = file_converter
            except ImportError:
                # Try installed package
                from markitdown import MarkItDown
                self._converter = MarkItDown()
        return self._converter
    
    async def convert(self, file_path: Union[str, Path], **kwargs) -> ConversionResult:
        """Convert file using MarkItDown."""
        try:
            converter = self._get_converter()
            
            # Use MarkItDown directly (simple case)
            if hasattr(converter, 'convert'):
                result = converter.convert(str(file_path))
                return ConversionResult(
                    text=result.text_content,
                    metadata={'title': result.title},
                    backend='markitdown',
                    success=True
                )
            else:
                # Use full convert_to_txt pipeline
                from converter_system.conversion_pipeline.file_unit import FileUnit
                file_unit = FileUnit(file_path=Path(file_path))
                converted = await converter(file_unit)
                return ConversionResult(
                    text=converted.data,
                    metadata={},
                    backend='convert_to_txt',
                    success=True
                )
        except Exception as e:
            return ConversionResult(
                text='',
                metadata={},
                backend='markitdown',
                success=False,
                error=str(e)
            )
    
    def get_supported_formats(self):
        """Return supported formats."""
        return ['pdf', 'docx', 'xlsx', 'pptx', 'html', 'xml', 
                'jpg', 'png', 'gif', 'mp3', 'wav', 'mp4']
```

**File:** `ipfs_datasets_py/file_converter/backends/omni_backend.py`

```python
"""Adapter for omni_converter_mk2."""

from pathlib import Path
from typing import Union
from ..converter import ConversionResult

class OmniBackend:
    """Backend using omni_converter_mk2."""
    
    def __init__(self, **options):
        self.options = options
        self._converter = None
    
    def _get_converter(self):
        """Lazy-load converter."""
        if self._converter is None:
            import sys
            omni_path = Path(__file__).parent.parent.parent / 'multimedia' / 'omni_converter_mk2'
            sys.path.insert(0, str(omni_path))
            from interfaces import make_api
            self._converter = make_api()
        return self._converter
    
    async def convert(self, file_path: Union[str, Path], **kwargs) -> ConversionResult:
        """Convert file using omni_converter_mk2."""
        try:
            converter = self._get_converter()
            result = converter.convert_file(str(file_path))
            
            return ConversionResult(
                text=result.content,
                metadata=result.metadata,
                backend='omni',
                success=True
            )
        except Exception as e:
            return ConversionResult(
                text='',
                metadata={},
                backend='omni',
                success=False,
                error=str(e)
            )
    
    def get_supported_formats(self):
        """Return supported formats."""
        return ['html', 'xml', 'txt', 'csv', 'ical',
                'jpg', 'png', 'gif', 'webp', 'svg',
                'mp3', 'wav', 'ogg', 'flac', 'aac',
                'mp4', 'webm', 'avi', 'mkv', 'mov',
                'pdf', 'json', 'docx', 'xlsx', 'zip']
```

**File:** `ipfs_datasets_py/file_converter/backends/native_backend.py`

```python
"""Native implementation (Phase 2+)."""

from pathlib import Path
from typing import Union
from ..converter import ConversionResult

class NativeBackend:
    """Native implementation - gradually built out in Phase 2+."""
    
    def __init__(self, **options):
        self.options = options
    
    async def convert(self, file_path: Union[str, Path], **kwargs) -> ConversionResult:
        """Convert file using native implementation."""
        file_path = Path(file_path)
        
        # Phase 2+: Implement native converters
        # For now, basic text file support
        if file_path.suffix.lower() in ['.txt', '.md', '.rst']:
            try:
                text = file_path.read_text()
                return ConversionResult(
                    text=text,
                    metadata={'format': file_path.suffix},
                    backend='native',
                    success=True
                )
            except Exception as e:
                return ConversionResult(
                    text='',
                    metadata={},
                    backend='native',
                    success=False,
                    error=str(e)
                )
        
        return ConversionResult(
            text='',
            metadata={},
            backend='native',
            success=False,
            error=f'Format {file_path.suffix} not yet implemented in native backend'
        )
    
    def get_supported_formats(self):
        """Return supported formats."""
        # Phase 2+: Expand this list as we implement
        return ['txt', 'md', 'rst']
```

---

## 📝 Usage Examples

### Example 1: Basic Conversion
```python
from ipfs_datasets_py.processors.file_converter import FileConverter

# Initialize converter (auto-selects best backend)
converter = FileConverter()

# Convert a file
result = await converter.convert('document.pdf')
print(f"Text: {result.text[:200]}...")
print(f"Backend used: {result.backend}")
```

### Example 2: GraphRAG Integration
```python
from ipfs_datasets_py.processors.file_converter import FileConverter
from ipfs_datasets_py.rag import GraphRAG

converter = FileConverter()
graph = GraphRAG()

# Convert and add to knowledge graph
result = await converter.convert('research_paper.pdf')
if result.success:
    await graph.add_document(
        result.text,
        metadata=result.metadata
    )
```

### Example 3: Batch Processing
```python
from ipfs_datasets_py.processors.file_converter import FileConverter
from pathlib import Path

converter = FileConverter()

# Find all PDFs
pdf_files = list(Path('documents/').rglob('*.pdf'))

# Convert in batches
results = await converter.convert_batch(pdf_files, max_concurrent=5)

# Process results
successful = [r for r in results if r.success]
failed = [r for r in results if not r.success]

print(f"Converted: {len(successful)}/{len(results)}")
```

### Example 4: Backend Selection
```python
from ipfs_datasets_py.processors.file_converter import FileConverter

# Use specific backend for rich metadata
omni_converter = FileConverter(backend='omni')
result = await omni_converter.convert('document.pdf')
print(result.metadata)  # Rich metadata

# Use specific backend for speed
fast_converter = FileConverter(backend='markitdown')
result = await fast_converter.convert('document.pdf')
print(result.text)  # Fast conversion
```

---

## 🔄 Migration Timeline

### Week 1-2: Phase 1 Implementation
- [x] Create file_converter module structure
- [ ] Implement FileConverter main class
- [ ] Create backend adapters (markitdown, omni, native)
- [ ] Add to setup.py as optional dependency
- [ ] Write basic tests
- [ ] Document usage

### Month 2: Phase 2 Start - High Priority Features
- [ ] Native async file converter
- [ ] Format detection
- [ ] Basic text extraction (txt, html, json)
- [ ] Unified error handling

### Month 3: Phase 2 Continue - Medium Priority
- [ ] Metadata extraction
- [ ] Async batch processing
- [ ] Progress tracking
- [ ] Resource management

### Month 4: Phase 2 Complete - Low Priority
- [ ] Text normalization
- [ ] Security validation
- [ ] Caching layer
- [ ] Format optimizations

### Month 5-6: Phase 3 (Optional)
- [ ] Full native implementation
- [ ] Deprecate external dependencies
- [ ] Performance optimization
- [ ] Complete test coverage

---

## 🧪 Testing Strategy

### Phase 1 Tests
```python
# test_file_converter.py

import pytest
from ipfs_datasets_py.processors.file_converter import FileConverter

@pytest.mark.asyncio
async def test_basic_conversion():
    """Test basic file conversion."""
    converter = FileConverter()
    result = await converter.convert('test_data/sample.txt')
    assert result.success
    assert len(result.text) > 0

@pytest.mark.asyncio
async def test_backend_selection():
    """Test explicit backend selection."""
    # MarkItDown backend
    converter1 = FileConverter(backend='markitdown')
    result1 = await converter1.convert('test_data/sample.pdf')
    assert result1.backend == 'markitdown'
    
    # Omni backend
    converter2 = FileConverter(backend='omni')
    result2 = await converter2.convert('test_data/sample.pdf')
    assert result2.backend == 'omni'

@pytest.mark.asyncio
async def test_batch_conversion():
    """Test batch processing."""
    converter = FileConverter()
    files = ['file1.txt', 'file2.txt', 'file3.txt']
    results = await converter.convert_batch(files)
    assert len(results) == 3
```

---

## 📚 Documentation Updates

### README.md Addition
```markdown
## File Conversion

Convert arbitrary file types to text for GraphRAG and knowledge graph processing.

### Quick Start

```python
from ipfs_datasets_py.processors.file_converter import FileConverter

converter = FileConverter()
result = await converter.convert('document.pdf')
print(result.text)
```

### Supported Formats

- Documents: PDF, DOCX, XLSX, PPTX, ODT, ODS
- Web: HTML, XML, CSS, JS
- Images: JPEG, PNG, GIF, WebP, SVG
- Audio: MP3, WAV, OGG, FLAC, AAC
- Video: MP4, WebM, AVI, MKV, MOV
- Archives: ZIP, TAR, RAR
- And 96+ more...

### Installation

```bash
# Basic conversion support
pip install ipfs-datasets-py[file_conversion]

# Full support (all formats)
pip install ipfs-datasets-py[file_conversion_full]
```

See [File Conversion Guide](docs/FILE_CONVERSION_INTEGRATION.md) for details.
```

---

## 🎯 Success Criteria

### Phase 1 Success
- ✅ Users can convert files with one line of code
- ✅ Works with GraphRAG immediately
- ✅ Backend selection working
- ✅ Batch processing functional
- ✅ Tests passing

### Phase 2 Success
- ✅ Core features implemented natively
- ✅ Performance equal or better than libraries
- ✅ Reduced external dependencies
- ✅ Comprehensive test coverage

### Phase 3 Success (Optional)
- ✅ Fully native implementation
- ✅ No external conversion dependencies
- ✅ Optimized for ipfs_datasets_py use cases

---

## 🚀 Getting Started

### For Users (Immediate)
```bash
# Install with file conversion support
pip install ipfs-datasets-py[file_conversion]

# Use immediately
python -c "
from ipfs_datasets_py.processors.file_converter import FileConverter
import asyncio

async def test():
    converter = FileConverter()
    result = await converter.convert('document.pdf')
    print(f'Converted: {len(result.text)} characters')

asyncio.run(test())
"
```

### For Developers (Contributing)
```bash
# Clone repo
git clone https://github.com/endomorphosis/ipfs_datasets_py
cd ipfs_datasets_py

# Install with dev dependencies
pip install -e ".[file_conversion,test]"

# Run tests
pytest tests/test_file_converter.py -v
```

---

## 💡 Key Advantages of This Approach

1. **Immediate Value** - Users get working conversion now
2. **Low Risk** - Using proven libraries initially
3. **Gradual Migration** - Reimplement incrementally
4. **Learn Best Practices** - Study both codebases as we go
5. **Flexibility** - Can keep library backends long-term if they work well
6. **Native Integration** - Eventually fully integrated with ipfs_datasets_py
7. **User Choice** - Users can pick backend based on needs

---

## 📖 Related Documentation

- [File Conversion Pros & Cons](file_conversion_pros_cons.md)
- [Systems Analysis](file_conversion_systems_analysis.md)
- [Merge Feasibility](file_conversion_merge_feasibility.md)
- [Multimedia README](../ipfs_datasets_py/multimedia/README.md)

---

**Status:** Phase 1 Implementation Ready  
**Next Step:** Create file_converter module  
**Timeline:** Week 1-2 for Phase 1  
**Maintainer:** ipfs_datasets_py team
