"""
Native implementation backend (Phase 2+).

This backend contains native implementations that are gradually built out
to replace external dependencies.

Phase 2: Integrated format detection and enhanced extractors.
"""

from pathlib import Path
from typing import Union
import logging

logger = logging.getLogger(__name__)


class NativeBackend:
    """
    Native implementation backend.
    
    Phase 1: Basic text file support only
    Phase 2: Format detection + Enhanced extractors (PDF, DOCX, XLSX, HTML)
    """
    
    def __init__(self, **options):
        """
        Initialize Native backend.
        
        Args:
            **options: Backend-specific options
        """
        self.options = options
        self._format_detector = None
        self._extractor_registry = None
        logger.debug("NativeBackend initialized with Phase 2 features")
    
    @property
    def format_detector(self):
        """Lazy-load format detector."""
        if self._format_detector is None:
            from ..format_detector import FormatDetector
            self._format_detector = FormatDetector()
        return self._format_detector
    
    @property
    def extractor_registry(self):
        """Lazy-load extractor registry."""
        if self._extractor_registry is None:
            from ..text_extractors import ExtractorRegistry
            self._extractor_registry = ExtractorRegistry()
        return self._extractor_registry
    
    async def convert(self, file_path: Union[str, Path], **kwargs):
        """
        Convert file using native implementation.
        
        Phase 2: Uses format detection and enhanced extractors.
        Supports: txt, md, json, csv, html, xml, pdf, docx, xlsx
        
        Args:
            file_path: Path to file to convert
            **kwargs: Additional options
            
        Returns:
            ConversionResult
        """
        from ..converter import ConversionResult
        
        try:
            file_path = Path(file_path)
            
            if not file_path.exists():
                return ConversionResult(
                    text='',
                    metadata={},
                    backend='native',
                    success=False,
                    error=f"File not found: {file_path}"
                )
            
            # Phase 2: Detect format using native detector
            mime_type = self.format_detector.detect_file(file_path)
            category = self.format_detector.get_category(mime_type) if mime_type else None
            
            suffix = file_path.suffix.lower()
            
            # Phase 2: Try enhanced extractors first (PDF, DOCX, XLSX, HTML)
            extraction_result = self.extractor_registry.extract(file_path)
            if extraction_result.success:
                # Convert to ConversionResult format
                metadata = extraction_result.metadata.copy()
                metadata.update({
                    'mime_type': mime_type,
                    'category': category,
                    'size': file_path.stat().st_size,
                    'filename': file_path.name,
                })
                return ConversionResult(
                    text=extraction_result.text,
                    metadata=metadata,
                    backend='native',
                    success=True
                )
            
            # Phase 1 fallback: Basic text formats
            if suffix in ['.txt', '.md', '.markdown', '.rst']:
                text = file_path.read_text(encoding='utf-8', errors='ignore')
                return ConversionResult(
                    text=text,
                    metadata={
                        'format': suffix[1:],
                        'mime_type': mime_type,
                        'category': category,
                        'size': file_path.stat().st_size,
                        'filename': file_path.name,
                    },
                    backend='native',
                    success=True
                )
            
            # Phase 1: JSON (simple parsing)
            elif suffix == '.json':
                import json
                data = json.loads(file_path.read_text(encoding='utf-8'))
                text = json.dumps(data, indent=2)
                return ConversionResult(
                    text=text,
                    metadata={
                        'format': 'json',
                        'mime_type': mime_type,
                        'category': category,
                        'size': file_path.stat().st_size,
                    },
                    backend='native',
                    success=True
                )
            
            # Phase 1: CSV (basic parsing)
            elif suffix == '.csv':
                import csv
                rows = []
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    reader = csv.reader(f)
                    for row in reader:
                        rows.append(' | '.join(row))
                text = '\n'.join(rows)
                return ConversionResult(
                    text=text,
                    metadata={
                        'format': 'csv',
                        'rows': len(rows),
                        'mime_type': mime_type,
                        'category': category,
                        'size': file_path.stat().st_size,
                    },
                    backend='native',
                    success=True
                )
            
            # Phase 1: XML (basic text extraction)
            elif suffix == '.xml':
                import xml.etree.ElementTree as ET
                try:
                    tree = ET.parse(file_path)
                    root = tree.getroot()
                    # Extract all text from XML
                    text = ' '.join(root.itertext())
                    return ConversionResult(
                        text=text,
                        metadata={
                            'format': 'xml',
                            'root_tag': root.tag,
                            'mime_type': mime_type,
                            'category': category,
                        },
                        backend='native',
                        success=True
                    )
                except Exception as e:
                    logger.warning(f"XML parsing failed, falling back to text: {e}")
                    text = file_path.read_text(encoding='utf-8', errors='ignore')
                    return ConversionResult(
                        text=text,
                        metadata={
                            'format': 'xml',
                            'mime_type': mime_type,
                            'category': category,
                        },
                        backend='native',
                        success=True
                    )
            
            # Unsupported format
            else:
                # Provide helpful error with format info
                format_info = f" (detected as {mime_type})" if mime_type else ""
                return ConversionResult(
                    text='',
                    metadata={'mime_type': mime_type, 'category': category},
                    backend='native',
                    success=False,
                    error=(
                        f"Format {suffix}{format_info} not yet implemented in native backend. "
                        f"Use backend='markitdown' or backend='omni' for this format, "
                        f"or install with: pip install ipfs-datasets-py[file_conversion_full]"
                    )
                )
                
        except Exception as e:
            logger.error(f"Native conversion error for {file_path}: {e}")
            return ConversionResult(
                text='',
                metadata={},
                backend='native',
                success=False,
                error=str(e)
            )
    
    def get_supported_formats(self):
        """
        Return list of currently supported formats (native implementation).
        
        Phase 2: Expanded with enhanced extractors.
        """
        formats = [
            'txt', 'md', 'markdown', 'rst',  # Plain text
            'json',                           # JSON
            'csv',                            # CSV
            'html', 'htm',                    # HTML (enhanced)
            'xml',                            # XML (basic)
        ]
        
        # Add formats from extractors
        extractor_formats = self.extractor_registry.get_supported_formats()
        for mime_type in extractor_formats:
            # Convert MIME types to extensions
            ext = self.format_detector.get_extension(mime_type)
            if ext and ext[1:] not in formats:  # Remove leading dot
                formats.append(ext[1:])
        
        return formats
