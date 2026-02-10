"""
Image processing module with OCR support.

Extracts text from images using Tesseract OCR (optional) and metadata.
Supports JPEG, PNG, GIF, WebP, SVG, BMP, TIFF, ICO, APNG formats.
"""

import logging
import mimetypes
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ImageResult:
    """Result from image processing."""
    text: str
    metadata: Dict[str, Any]
    success: bool
    error: Optional[str] = None
    ocr_available: bool = False


class ImageProcessor:
    """
    Process images with optional OCR text extraction.
    
    Supports:
    - JPEG, PNG, GIF, WebP, SVG, BMP, TIFF, ICO, APNG
    - OCR with Tesseract (optional)
    - Rich metadata extraction
    - Graceful fallback when OCR unavailable
    """
    
    def __init__(
        self,
        ocr_enabled: bool = True,
        ocr_lang: str = 'eng',
        ocr_config: str = ''
    ):
        """
        Initialize image processor.
        
        Args:
            ocr_enabled: Enable OCR text extraction
            ocr_lang: Tesseract language (default: 'eng')
            ocr_config: Additional Tesseract config options
        """
        self.ocr_enabled = ocr_enabled
        self.ocr_lang = ocr_lang
        self.ocr_config = ocr_config
        
        # Try to import OCR dependencies
        self.PIL_available = False
        self.pytesseract_available = False
        self.cairosvg_available = False
        
        try:
            from PIL import Image
            self.PIL = Image
            self.PIL_available = True
        except ImportError:
            logger.warning("PIL/Pillow not available - image processing disabled")
            
        if ocr_enabled:
            try:
                import pytesseract
                self.pytesseract = pytesseract
                self.pytesseract_available = True
            except ImportError:
                logger.warning("pytesseract not available - OCR disabled")
                
        try:
            import cairosvg
            self.cairosvg = cairosvg
            self.cairosvg_available = True
        except ImportError:
            logger.debug("cairosvg not available - SVG OCR will use XML parsing only")
    
    def extract_text(self, file_path: str) -> Dict[str, Any]:
        """
        Extract text and metadata from image.
        
        Args:
            file_path: Path to image file
            
        Returns:
            Dict with 'text', 'metadata', 'success', 'error', 'ocr_available'
        """
        if not self.PIL_available:
            return {
                'text': '',
                'metadata': {},
                'success': False,
                'error': 'PIL/Pillow not available',
                'ocr_available': False
            }
        
        try:
            file_path = Path(file_path)
            
            # Check if SVG
            mime_type, _ = mimetypes.guess_type(str(file_path))
            if mime_type == 'image/svg+xml' or file_path.suffix.lower() == '.svg':
                return self._extract_svg_text(file_path)
            
            # Open image
            image = self.PIL.open(file_path)
            
            # Extract metadata
            metadata = self._extract_metadata(image, file_path)
            
            # Extract text via OCR if enabled
            text = ''
            ocr_available = False
            
            if self.ocr_enabled and self.pytesseract_available:
                try:
                    text = self.pytesseract.image_to_string(
                        image,
                        lang=self.ocr_lang,
                        config=self.ocr_config
                    ).strip()
                    ocr_available = True
                    
                    # Try to get confidence score
                    try:
                        data = self.pytesseract.image_to_data(
                            image,
                            lang=self.ocr_lang,
                            output_type=self.pytesseract.Output.DICT
                        )
                        confidences = [int(c) for c in data['conf'] if c != '-1']
                        if confidences:
                            metadata['ocr_confidence'] = sum(confidences) / len(confidences)
                    except Exception:
                        pass
                        
                except Exception as e:
                    logger.warning(f"OCR failed for {file_path}: {e}")
                    text = ''
            
            return {
                'text': text,
                'metadata': metadata,
                'success': True,
                'error': None,
                'ocr_available': ocr_available
            }
            
        except Exception as e:
            logger.error(f"Error processing image {file_path}: {e}")
            return {
                'text': '',
                'metadata': {},
                'success': False,
                'error': str(e),
                'ocr_available': False
            }
    
    def _extract_svg_text(self, file_path: Path) -> Dict[str, Any]:
        """Extract text from SVG file."""
        try:
            # Parse SVG XML for text elements
            import xml.etree.ElementTree as ET
            
            tree = ET.parse(file_path)
            root = tree.getroot()
            
            # Extract text from text elements
            texts = []
            for elem in root.iter():
                if elem.tag.endswith('text') or elem.tag.endswith('tspan'):
                    if elem.text:
                        texts.append(elem.text.strip())
            
            text_content = '\n'.join(texts)
            
            # Get SVG metadata
            metadata = {
                'format': 'SVG',
                'file_size': file_path.stat().st_size,
            }
            
            # Try to get viewBox for dimensions
            viewbox = root.get('viewBox')
            if viewbox:
                try:
                    _, _, width, height = map(float, viewbox.split())
                    metadata['size'] = (int(width), int(height))
                except Exception:
                    pass
            
            # If OCR is enabled and cairosvg available, try OCR on rendered SVG
            ocr_available = False
            if self.ocr_enabled and self.pytesseract_available and self.cairosvg_available:
                try:
                    # Convert SVG to PNG in memory
                    png_data = self.cairosvg.svg2png(url=str(file_path))
                    
                    # Open PNG with PIL
                    from io import BytesIO
                    image = self.PIL.open(BytesIO(png_data))
                    
                    # Extract text via OCR
                    ocr_text = self.pytesseract.image_to_string(
                        image,
                        lang=self.ocr_lang,
                        config=self.ocr_config
                    ).strip()
                    
                    # Combine XML text and OCR text
                    if ocr_text and ocr_text not in text_content:
                        text_content = f"{text_content}\n{ocr_text}".strip()
                    
                    ocr_available = True
                    
                except Exception as e:
                    logger.debug(f"SVG OCR failed: {e}")
            
            return {
                'text': text_content,
                'metadata': metadata,
                'success': True,
                'error': None,
                'ocr_available': ocr_available
            }
            
        except Exception as e:
            logger.error(f"Error processing SVG {file_path}: {e}")
            return {
                'text': '',
                'metadata': {},
                'success': False,
                'error': str(e),
                'ocr_available': False
            }
    
    def _extract_metadata(self, image, file_path: Path) -> Dict[str, Any]:
        """Extract metadata from PIL Image object."""
        metadata = {
            'format': image.format or 'Unknown',
            'size': image.size,  # (width, height)
            'mode': image.mode,  # RGB, RGBA, L, etc.
            'file_size': file_path.stat().st_size,
        }
        
        # DPI info
        if hasattr(image, 'info') and 'dpi' in image.info:
            metadata['dpi'] = image.info['dpi']
        
        # Transparency
        if image.mode in ('RGBA', 'LA', 'P'):
            metadata['has_transparency'] = True
        else:
            metadata['has_transparency'] = False
        
        # Animation (GIF, APNG)
        if hasattr(image, 'n_frames'):
            metadata['animated'] = image.n_frames > 1
            if image.n_frames > 1:
                metadata['n_frames'] = image.n_frames
        else:
            metadata['animated'] = False
        
        # EXIF data if available
        try:
            if hasattr(image, '_getexif') and image._getexif():
                exif = image._getexif()
                if exif:
                    # Add some common EXIF fields
                    from PIL.ExifTags import TAGS
                    exif_data = {}
                    for tag_id, value in exif.items():
                        tag = TAGS.get(tag_id, tag_id)
                        if tag in ('DateTime', 'Make', 'Model', 'Software', 'Orientation'):
                            exif_data[tag] = str(value)
                    if exif_data:
                        metadata['exif'] = exif_data
        except Exception:
            pass
        
        return metadata


# Convenience functions
def extract_image_text(
    file_path: str,
    ocr_enabled: bool = True,
    ocr_lang: str = 'eng'
) -> Dict[str, Any]:
    """
    Extract text from image file.
    
    Args:
        file_path: Path to image file
        ocr_enabled: Enable OCR
        ocr_lang: OCR language
        
    Returns:
        Dict with text, metadata, success, error, ocr_available
    """
    processor = ImageProcessor(ocr_enabled=ocr_enabled, ocr_lang=ocr_lang)
    return processor.extract_text(file_path)


def is_image_file(file_path: str) -> bool:
    """Check if file is a supported image format."""
    supported_extensions = {
        '.jpg', '.jpeg', '.png', '.gif', '.webp',
        '.svg', '.bmp', '.tiff', '.tif', '.ico'
    }
    
    file_path = Path(file_path)
    return file_path.suffix.lower() in supported_extensions


# Supported image MIME types
SUPPORTED_IMAGE_MIME_TYPES = {
    'image/jpeg',
    'image/png',
    'image/gif',
    'image/webp',
    'image/svg+xml',
    'image/bmp',
    'image/tiff',
    'image/x-icon',
    'image/vnd.microsoft.icon',
}
