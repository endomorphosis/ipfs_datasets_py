"""
OCR processor implementation for image format handlers.

This module provides the PyTesseractProcessor class for extracting text 
from images using the Tesseract OCR engine via pytesseract.
"""
from datetime import datetime
import io
from typing import Any, Optional, Tuple


from logger import logger
from core.content_extractor.processors.by_ability._image_processor import ImageProcessor


# Try to import pytesseract and PIL
try:
    import pytesseract
    from PIL import Image, ExifTags
    TESSERACT_AVAILABLE = True
except ImportError:
    logger.warning("pytesseract or PIL not available, OCR functionality will be disabled")
    TESSERACT_AVAILABLE = False

class PyTesseractProcessor(ImageProcessor):
    """
    Processor for extracting text from images using Tesseract OCR.
    
    This processor uses pytesseract to perform OCR on images, extracting text,
    metadata, and visual features.
    """
    
    def __init__(self):
        """Initialize the PyTesseract processor."""
        self._supported_formats = ["jpeg", "jpg", "png", "bmp", "tiff", "tif", "gif", "webp"]
        
        # Check if tesseract is installed and available
        if TESSERACT_AVAILABLE:
            try:
                # Test pytesseract availability by getting version
                tesseract_version = pytesseract.get_tesseract_version()
                logger.info(f"Tesseract OCR version {tesseract_version} detected")
            except Exception as e:
                logger.warning(f"Tesseract OCR not available: {e}")
                self.supported_formats = []
    
    def can_process(self, format_name: str) -> bool:
        """
        Check if this processor can handle the given format.
        
        Args:
            format_name: The name of the format to check.
            
        Returns:
            True if this processor can handle the format, False otherwise.
        """
        if not TESSERACT_AVAILABLE:
            return False
        return format_name.lower() in self.supported_formats
    
    @property
    def supported_formats(self) -> list[str]:
        """
        Get the list of formats supported by this processor.
        
        Returns:
            A list of format names supported by this processor.
        """
        return self._supported_formats if TESSERACT_AVAILABLE else []
    
    def get_processor_info(self) -> dict[str, Any]:
        """
        Get information about this processor.
        
        Returns:
            A dictionary containing information about this processor.
        """
        info = {
            "name": "PyTesseractProcessor",
            "available": TESSERACT_AVAILABLE,
            "version": str(pytesseract.get_tesseract_version()) if TESSERACT_AVAILABLE else "N/A",
            "supported_formats": self.supported_formats
        }
        
        if TESSERACT_AVAILABLE:
            # Add available languages
            try:
                info["available_languages"] = pytesseract.get_languages()
            except:
                info["available_languages"] = ["eng"]  # Default to English if we can't detect
        
        return info
    
    def extract_text(self, data: bytes, options: dict[str, Any]) -> str:
        """
        Extract text from an image using OCR.
        
        Args:
            data: The binary data of the image.
            options: Processing options including:
                - language: OCR language (default: 'eng')
                - config: Additional Tesseract configuration
                
        Returns:
            Extracted text from the image.
            
        Raises:
            ValueError: If pytesseract is not available or the image is invalid.
        """
        if not TESSERACT_AVAILABLE:
            raise ValueError("Tesseract OCR not available")
        
        # Get options
        language = options.get('language', 'eng')
        config = options.get('config', '')
        
        try:
            # Open the image with PIL
            image = Image.open(io.BytesIO(data))
            
            # Perform OCR
            text = pytesseract.image_to_string(image, lang=language, config=config)

            # Clean up extracted text
            return text.strip()
            
        except Exception as e:
            logger.error(f"Error extracting text with Tesseract OCR: {e}")
            raise ValueError(f"Failed to extract text: {e}")
    
    def extract_metadata(self, data: bytes, options: dict[str, Any]) -> dict[str, Any]:
        """
        Extract metadata from an image.
        
        Args:
            data: The binary data of the image.
            options: Processing options.
            
        Returns:
            Metadata extracted from the image.
            
        Raises:
            ValueError: If PIL is not available or the image is invalid.
        """
        if not TESSERACT_AVAILABLE:  # TESSERACT_AVAILABLE also checks for PIL
            raise ValueError("PIL not available for metadata extraction")
        
        try:
            # Open the image with PIL
            image = Image.open(io.BytesIO(data))
            
            # Basic metadata
            metadata = {
                "format": image.format.lower() if image.format else "unknown",
                "mode": image.mode,
                "width": image.width,
                "height": image.height,
                "size": len(data),
                "aspect_ratio": image.width / image.height if image.height > 0 else 0,
                "has_transparency": image.mode == 'RGBA' or 'transparency' in image.info,
                "extraction_time": datetime.now().isoformat()
            }
            
            # Get EXIF data if available
            if hasattr(image, '_getexif') and image._getexif():
                exif = {
                    ExifTags.TAGS.get(tag, tag): value
                    for tag, value in image._getexif().items()
                    if tag in ExifTags.TAGS  # Only include known tags
                }
                
                # Clean up EXIF data - convert bytes to strings, etc.
                clean_exif = {}
                for key, value in exif.items():
                    if isinstance(value, bytes):
                        try:
                            clean_exif[key] = value.decode('utf-8')
                        except UnicodeDecodeError:
                            clean_exif[key] = str(value)
                    else:
                        clean_exif[key] = value
                
                metadata["exif"] = clean_exif
            
            return metadata
            
        except Exception as e:
            logger.error(f"Error extracting image metadata: {e}")
            raise ValueError(f"Failed to extract metadata: {e}")
    
    def extract_features(self, data: bytes, options: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Extract visual features from an image.
        
        Args:
            data: The binary data of the image.
            options: Processing options including:
                - include_hocr: Whether to include HOCR output (default: False)
                - include_boxes: Whether to include text bounding boxes (default: False)
                
        Returns:
            A list of features extracted from the image.
            
        Raises:
            ValueError: If pytesseract is not available or the image is invalid.
        """
        if not TESSERACT_AVAILABLE:
            raise ValueError("Tesseract OCR not available")
        
        # Get options
        include_hocr = options.get('include_hocr', False)
        include_boxes = options.get('include_boxes', False)
        language = options.get('language', 'eng')
        
        features = []
        
        try:
            # Open the image with PIL
            image = Image.open(io.BytesIO(data))
            
            # Add basic image data
            features.append({
                "type": "dimensions",
                "content": {
                    "width": image.width,
                    "height": image.height,
                    "mode": image.mode
                }
            })
            
            # Add color information
            if image.mode in ('RGB', 'RGBA'):
                try:
                    # Get a simplified color histogram (just the frequency of most common colors)
                    colors = image.convert('RGB').getcolors(maxcolors=10)
                    if colors:
                        features.append({
                            "type": "colors",
                            "content": {
                                "common_colors": [
                                    {"rgb": color[1], "frequency": color[0]} 
                                    for color in sorted(colors, key=lambda x: x[0], reverse=True)
                                ]
                            }
                        })
                except:
                    pass  # Skip if histogram generation fails
            
            # Add OCR data if requested
            if include_hocr:
                try:
                    hocr = pytesseract.image_to_pdf_or_hocr(image, extension='hocr', lang=language)
                    features.append({
                        "type": "hocr",
                        "content": hocr.decode('utf-8') if isinstance(hocr, bytes) else hocr
                    })
                except Exception as e:
                    logger.warning(f"Failed to generate HOCR: {e}")
            
            # Add text bounding boxes if requested
            if include_boxes:
                try:
                    boxes = pytesseract.image_to_data(image, lang=language, output_type=pytesseract.Output.DICT)
                    
                    # Convert to a more readable format
                    text_regions = []
                    for i in range(len(boxes['text'])):
                        if boxes['text'][i].strip():  # Only include non-empty text
                            text_regions.append({
                                "text": boxes['text'][i],
                                "conf": boxes['conf'][i],
                                "bbox": {
                                    "x": boxes['left'][i],
                                    "y": boxes['top'][i],
                                    "width": boxes['width'][i],
                                    "height": boxes['height'][i]
                                }
                            })
                    
                    features.append({
                        "type": "text_regions",
                        "content": text_regions
                    })
                except Exception as e:
                    logger.warning(f"Failed to generate text regions: {e}")
            
            return features
            
        except Exception as e:
            logger.error(f"Error extracting image features: {e}")
            raise ValueError(f"Failed to extract features: {e}")
    
    def process_image(self, data: bytes, options: dict[str, Any]) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        """
        Process an image completely, extracting text, metadata, and features.
        
        Args:
            data: The binary data of the image.
            options: Processing options.
            
        Returns:
            A tuple of (text content, metadata, sections).
            
        Raises:
            ValueError: If pytesseract is not available or the image is invalid.
        """
        if not TESSERACT_AVAILABLE:
            raise ValueError("Tesseract OCR not available")
        
        try:
            # Extract all components
            text = self.extract_text(data, options)
            metadata = self.extract_metadata(data, options)
            features = self.extract_features(data, options)
            
            # Generate sections for the output
            sections = []
            
            # Add image info section
            sections.append({
                "type": "image_info",
                "content": {
                    "format": metadata.get("format", "unknown"),
                    "dimensions": f"{metadata.get('width', 0)}x{metadata.get('height', 0)}",
                    "mode": metadata.get("mode", "unknown")
                }
            })
            
            # Add OCR text section
            sections.append({
                "type": "ocr_text",
                "content": text
            })
            
            # Include visual features
            for feature in features:
                sections.append(feature)
            
            # Create human-readable text content
            text_content = []
            text_content.append(f"Image: {metadata.get('width', 0)}x{metadata.get('height', 0)} {metadata.get('format', 'image').upper()}")
            
            if "exif" in metadata and len(metadata["exif"]) > 0:
                text_content.append("\nEXIF Metadata:")
                for key, value in metadata["exif"].items():
                    if key in ["DateTime", "Make", "Model", "Software", "Artist", "Copyright"]:
                        text_content.append(f"- {key}: {value}")
            
            text_content.append("\nExtracted Text (OCR):")
            text_content.append(text)
            
            return "\n".join(text_content), metadata, sections
            
        except Exception as e:
            logger.error(f"Error processing image: {e}")
            raise ValueError(f"Failed to process image: {e}")


# Create a global instance of the processor
ocr_processor = PyTesseractProcessor()
