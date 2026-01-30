"""
Native implementation backend (Phase 2+).

This backend contains native implementations that are gradually built out
to replace external dependencies.
"""

from pathlib import Path
from typing import Union
import logging

logger = logging.getLogger(__name__)


class NativeBackend:
    """
    Native implementation backend.
    
    Phase 1: Basic text file support only
    Phase 2+: Gradually add more formats as we reimplement features
    """
    
    def __init__(self, **options):
        """
        Initialize Native backend.
        
        Args:
            **options: Backend-specific options
        """
        self.options = options
        logger.debug("NativeBackend initialized (limited format support)")
    
    async def convert(self, file_path: Union[str, Path], **kwargs):
        """
        Convert file using native implementation.
        
        Currently supports: txt, md, rst, json, xml, html, csv
        Phase 2+: Will add more formats
        
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
            
            suffix = file_path.suffix.lower()
            
            # Phase 1: Basic text formats
            if suffix in ['.txt', '.md', '.markdown', '.rst']:
                text = file_path.read_text(encoding='utf-8', errors='ignore')
                return ConversionResult(
                    text=text,
                    metadata={
                        'format': suffix[1:],
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
                        'size': file_path.stat().st_size,
                    },
                    backend='native',
                    success=True
                )
            
            # Phase 1: HTML (basic - just extract text)
            elif suffix in ['.html', '.htm']:
                try:
                    from bs4 import BeautifulSoup
                    html = file_path.read_text(encoding='utf-8', errors='ignore')
                    soup = BeautifulSoup(html, 'html.parser')
                    text = soup.get_text(separator='\n', strip=True)
                    return ConversionResult(
                        text=text,
                        metadata={
                            'format': 'html',
                            'title': soup.title.string if soup.title else None,
                        },
                        backend='native',
                        success=True
                    )
                except ImportError:
                    # Fallback: basic regex stripping
                    import re
                    html = file_path.read_text(encoding='utf-8', errors='ignore')
                    text = re.sub('<[^<]+?>', '', html)
                    return ConversionResult(
                        text=text,
                        metadata={'format': 'html'},
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
                        },
                        backend='native',
                        success=True
                    )
                except Exception as e:
                    logger.warning(f"XML parsing failed, falling back to text: {e}")
                    text = file_path.read_text(encoding='utf-8', errors='ignore')
                    return ConversionResult(
                        text=text,
                        metadata={'format': 'xml'},
                        backend='native',
                        success=True
                    )
            
            # Unsupported format
            else:
                return ConversionResult(
                    text='',
                    metadata={},
                    backend='native',
                    success=False,
                    error=(
                        f"Format {suffix} not yet implemented in native backend. "
                        f"Use backend='markitdown' or backend='omni' for this format, "
                        f"or install with: pip install ipfs-datasets-py[file_conversion]"
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
        """Return list of currently supported formats (native implementation)."""
        # Phase 1: Basic formats only
        # Phase 2+: Expand as we reimplement
        return [
            'txt', 'md', 'markdown', 'rst',  # Plain text
            'json',                           # JSON
            'csv',                            # CSV
            'html', 'htm',                    # HTML (basic)
            'xml',                            # XML (basic)
        ]
