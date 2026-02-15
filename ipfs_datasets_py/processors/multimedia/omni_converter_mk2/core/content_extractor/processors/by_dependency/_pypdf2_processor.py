"""
PDF processor implementation using PyPDF2.

This module provides a concrete implementation of DocumentProcessor for PDF files
using the PyPDF2 library.
"""

try:
    import PyPDF2
    PYPDF2_AVAILABLE = True
except ImportError:
    PYPDF2_AVAILABLE = False

    # Mock PyPDF2 for when it's not available
    class MockPyPDF2:

        class PdfReader:
            def __init__(self, *args, **kwargs):
                raise ImportError("PyPDF2 is not installed")

        __version__ = "mock"

    PyPDF2 = MockPyPDF2()

from datetime import datetime
import io
import re
from typing import Any, TypeVar, Optional

PdfReader = TypeVar('PdfReader')

import PyPDF2


from core.content_extractor.processors.document_processor import DocumentProcessor
from logger import logger


def load_pdf_pypdf2(
    data: bytes,
    options: Optional[dict[str, Any]] = None
) -> 'PdfReader':
    # Create a file-like object from the bytes
    pdf_file = io.BytesIO(data)

    # Open the PDF file
    reader = PyPDF2.PdfReader(pdf_file)

    # Check if the PDF is encrypted # TODO validate this password logic
    if reader.is_encrypted:
        # Attempt to decrypt the PDF if a password is provided in options
        password = options.get('password', None)
        if password:
            try:
                reader.decrypt(password)
            except Exception as e:
                logger.error(f"Failed to decrypt PDF: {e}")
                raise ValueError("Failed to decrypt PDF with provided password")
        else:
            logger.warning("PDF is encrypted but no password provided, cannot read content")
            raise ValueError("PDF is encrypted and no password provided")
    return reader


def _extract_outline_pypdf2(self, outline, structure, level=0):
    """Helper method to extract outline/bookmarks from the PDF.""" # TODO validate this method
    match outline:
        case None:
            return
        case list():
            for item in outline:
                _extract_outline_pypdf2(item, structure, level)
        case _:
            # Add outline item to structure
            if hasattr(outline, '/Title') and hasattr(outline, '/Page'):
                structure.append({
                    "type": "bookmark",
                    "level": level,
                    "title": outline['/Title'],
                    "page": outline['/Page']
                })
            
            # Process any children
            if hasattr(outline, '/Count') and outline['/Count'] > 0 and hasattr(outline, '/Kids'):
                _extract_outline_pypdf2(outline['/Kids'], structure, level + 1)



def extract_text(
    data: bytes, 
    options: Optional[dict[str, Any]] = None
) -> str:
    # Create a file-like object from the bytes
    pdf_file = io.BytesIO(data)
    
    # Open the PDF file
    reader = PyPDF2.PdfReader(pdf_file)
    
    # Extract text from each page
    text_parts = []
    
    for page_num, page in enumerate(reader.pages):
        # Extract text from the page
        text = page.extract_text()
        
        # Add page number and text
        if text:
            text_parts.append(f"--- Page {page_num + 1} ---")
            text_parts.append(text)
    
    # Join all text parts
    return "\n\n".join(text_parts)


def extract_metadata_pypdf2(
    data: bytes, 
    options: Optional[dict[str, Any]] = None
) -> str:
    # Create a file-like object from the bytes
    pdf_file = io.BytesIO(data)
    
    # Open the PDF file
    reader = PyPDF2.PdfReader(pdf_file)
    
    # Extract document info
    metadata = {}
    
    # Get basic information
    metadata["page_count"] = len(reader.pages)
    metadata["is_encrypted"] = reader.is_encrypted
    
    # Extract document information dictionary if available
    if hasattr(reader, "metadata") and reader.metadata:
        doc_info = reader.metadata
        
        # Map common metadata fields
        field_mapping = {
            "/Title": "title",
            "/Author": "author",
            "/Subject": "subject",
            "/Keywords": "keywords",
            "/Creator": "creator",
            "/Producer": "producer",
            "/CreationDate": "creation_date",
            "/ModDate": "modification_date"
        }
        
        for key, new_key in field_mapping.items():
            if key in doc_info:
                value = doc_info[key]
                # Convert PDF date strings to ISO format if possible
                if key in ["/CreationDate", "/ModDate"] and value:
                    date_str = str(value)
                    # Handle common PDF date format: D:YYYYMMDDHHmmSS
                    date_match = re.match(r'D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})', date_str)
                    if date_match:
                        try:
                            year, month, day, hour, minute, second = map(int, date_match.groups())
                            dt = datetime(year, month, day, hour, minute, second)
                            value = dt.isoformat()
                        except (ValueError, OverflowError):
                            # If date parsing fails, keep the original string
                            pass
                metadata[new_key] = value
    
    # Extract file size
    metadata["file_size_bytes"] = len(data)
    
    # Extract PDF version if available
    if hasattr(reader, "pdf_header"):
        metadata["pdf_version"] = reader.pdf_header
    
    return metadata


def extract_structure_pypdf2(
    data: bytes, 
    options: Optional[dict[str, Any]] = None
) -> list[dict[str, Any]]:
    
    # Create a file-like object from the bytes
    pdf_file = io.BytesIO(data)
    
    # Open the PDF file
    reader = PyPDF2.PdfReader(pdf_file)
    
    # Extract structure
    structure = []
    
    # Add document as a section
    structure.append({
        "type": "document",
        "content": "PDF Document"
    })
    
    # Add one section per page
    for page_num, page in enumerate(reader.pages):
        # Extract text from the page
        text = page.extract_text()
        
        # Add page section
        structure.append({
            "type": "page",
            "page_number": page_num + 1,
            "content": text[:1000] + ("..." if len(text) > 1000 else "")
        })
        
        # Get page dimensions
        if "/MediaBox" in page:
            media_box = page["/MediaBox"]
            if isinstance(media_box, list) and len(media_box) >= 4:
                structure.append({
                    "type": "dimensions",
                    "page_number": page_num + 1,
                    "width": float(media_box[2]),
                    "height": float(media_box[3])
                })
    
    # Extract outline/bookmarks if available
    if reader.outline:
        _extract_outline_pypdf2(reader.outline, structure)

    return structure






class PyPDF2Processor:
    """
    PDF processor implementation using PyPDF2.
    
    This class provides functionality to extract text, metadata, and structure
    from PDF files using the PyPDF2 library.
    """
    
    def __init__(self):
        """Initialize the PDF processor."""
        self._supported_formats = ["pdf"]
    
    def can_process(self, format_name: str) -> bool:
        """
        Check if this processor can handle the given format.
        
        Args:
            format_name: The name of the format to check.
            
        Returns:
            True if this processor can handle the format and PyPDF2 is available,
            False otherwise.
        """
        return PYPDF2_AVAILABLE and format_name.lower() in self.supported_formats
    
    @property
    def supported_formats(self) -> list[str]:
        """
        Get the list of formats supported by this processor.
        
        Returns:
            A list of format names supported by this processor.
        """
        return self._supported_formats if PYPDF2_AVAILABLE else []
    
    def get_processor_info(self) -> dict[str, Any]:
        """
        Get information about this processor.
        
        Returns:
            A dictionary containing information about this processor.
        """
        info = {
            "name": "PyPDF2Processor",
            "supported_formats": self.supported_formats,
            "available": PYPDF2_AVAILABLE
        }
        
        if PYPDF2_AVAILABLE:
            info["version"] = PyPDF2.__version__
        
        return info
    
    def extract_text(self, data: bytes, options: dict[str, Any]) -> str:
        """
        Extract plain text from a PDF document.
        
        Args:
            data: The binary data of the PDF document.
            options: Processing options.
            
        Returns:
            Extracted text from the PDF document.
            
        Raises:
            ValueError: If PyPDF2 is not available or the data cannot be processed as a PDF.
        """
        if not PYPDF2_AVAILABLE:
            raise ValueError("PyPDF2 is not available for PDF text extraction")
        
        try:
            # Create a file-like object from the bytes
            pdf_file = io.BytesIO(data)
            
            # Open the PDF file
            reader = PyPDF2.PdfReader(pdf_file)
            
            # Extract text from each page
            text_parts = []
            
            for page_num, page in enumerate(reader.pages):
                # Extract text from the page
                text = page.extract_text()
                
                # Add page number and text
                if text:
                    text_parts.append(f"--- Page {page_num + 1} ---")
                    text_parts.append(text)
            
            # Join all text parts
            return "\n\n".join(text_parts)
            
        except Exception as e:
            logger.error(f"Error extracting text from PDF: {e}")
            raise ValueError(f"Error extracting text from PDF: {e}")
    
    def extract_metadata(self, data: bytes, options: dict[str, Any]) -> dict[str, Any]:
        """
        Extract metadata from a PDF document.
        
        Args:
            data: The binary data of the PDF document.
            options: Processing options.
            
        Returns:
            Metadata extracted from the PDF document.
            
        Raises:
            ValueError: If PyPDF2 is not available or the data cannot be processed as a PDF.
        """
        if not PYPDF2_AVAILABLE:
            raise ValueError("PyPDF2 is not available for PDF metadata extraction")
        
        try:
            # Create a file-like object from the bytes
            pdf_file = io.BytesIO(data)
            
            # Open the PDF file
            reader = PyPDF2.PdfReader(pdf_file)
            
            # Extract document info
            metadata = {}
            
            # Get basic information
            metadata["page_count"] = len(reader.pages)
            metadata["is_encrypted"] = reader.is_encrypted
            
            # Extract document information dictionary if available
            if hasattr(reader, "metadata") and reader.metadata:
                doc_info = reader.metadata
                
                # Map common metadata fields
                field_mapping = {
                    "/Title": "title",
                    "/Author": "author",
                    "/Subject": "subject",
                    "/Keywords": "keywords",
                    "/Creator": "creator",
                    "/Producer": "producer",
                    "/CreationDate": "creation_date",
                    "/ModDate": "modification_date"
                }
                
                for key, new_key in field_mapping.items():
                    if key in doc_info:
                        value = doc_info[key]
                        # Convert PDF date strings to ISO format if possible
                        if key in ["/CreationDate", "/ModDate"] and value:
                            date_str = str(value)
                            # Handle common PDF date format: D:YYYYMMDDHHmmSS
                            date_match = re.match(r'D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})', date_str)
                            if date_match:
                                try:
                                    year, month, day, hour, minute, second = map(int, date_match.groups())
                                    dt = datetime(year, month, day, hour, minute, second)
                                    value = dt.isoformat()
                                except (ValueError, OverflowError):
                                    # If date parsing fails, keep the original string
                                    pass
                        metadata[new_key] = value
            
            # Extract file size
            metadata["file_size_bytes"] = len(data)
            
            # Extract PDF version if available
            if hasattr(reader, "pdf_header"):
                metadata["pdf_version"] = reader.pdf_header
            
            return metadata
            
        except Exception as e:
            logger.error(f"Error extracting metadata from PDF: {e}")
            raise ValueError(f"Error extracting metadata from PDF: {e}")
    
    def extract_structure(self, data: bytes, options: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Extract structural elements from a PDF document.
        
        Args:
            data: The binary data of the PDF document.
            options: Processing options.
            
        Returns:
            A list of structural elements extracted from the PDF document.
            
        Raises:
            ValueError: If PyPDF2 is not available or the data cannot be processed as a PDF.
        """
        if not PYPDF2_AVAILABLE:
            raise ValueError("PyPDF2 is not available for PDF structure extraction")
        
        try:
            # Create a file-like object from the bytes
            pdf_file = io.BytesIO(data)
            
            # Open the PDF file
            reader = PyPDF2.PdfReader(pdf_file)
            
            # Extract structure
            structure = []
            
            # Add document as a section
            structure.append({
                "type": "document",
                "content": "PDF Document"
            })
            
            # Add one section per page
            for page_num, page in enumerate(reader.pages):
                # Extract text from the page
                text = page.extract_text()
                
                # Add page section
                structure.append({
                    "type": "page",
                    "page_number": page_num + 1,
                    "content": text[:1000] + ("..." if len(text) > 1000 else "")
                })
                
                # Get page dimensions
                if "/MediaBox" in page:
                    media_box = page["/MediaBox"]
                    if isinstance(media_box, list) and len(media_box) >= 4:
                        structure.append({
                            "type": "dimensions",
                            "page_number": page_num + 1,
                            "width": float(media_box[2]),
                            "height": float(media_box[3])
                        })
            
            # Extract outline/bookmarks if available
            if reader.outline:
                self._extract_outline(reader.outline, structure)
            
            return structure
            
        except Exception as e:
            logger.error(f"Error extracting structure from PDF: {e}")
            raise ValueError(f"Error extracting structure from PDF: {e}")
    
    def _extract_outline(self, outline, structure, level=0):
        """Helper method to extract outline/bookmarks from the PDF.""" # TODO validate this method
        if not outline:
            return
        
        if isinstance(outline, list):
            for item in outline:
                self._extract_outline(item, structure, level)
        else:
            # Add outline item to structure
            if hasattr(outline, '/Title') and hasattr(outline, '/Page'):
                structure.append({
                    "type": "bookmark",
                    "level": level,
                    "title": outline['/Title'],
                    "page": outline['/Page']
                })
            
            # Process any children
            if hasattr(outline, '/Count') and outline['/Count'] > 0 and hasattr(outline, '/Kids'):
                self._extract_outline(outline['/Kids'], structure, level + 1)
    
    def process_document(self, data: bytes, options: dict[str, Any]) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        """
        Process a PDF document completely, extracting text, metadata, and structure.
        
        Args:
            data: The binary data of the PDF document.
            options: Processing options.
            
        Returns:
            A tuple of (text content, metadata, sections).
            
        Raises:
            ValueError: If PyPDF2 is not available or the data cannot be processed as a PDF.
        """
        if not PYPDF2_AVAILABLE:
            raise ValueError("PyPDF2 is not available for PDF processing")
        
        try:
            # Extract text, metadata, and structure
            text = self.extract_text(data, options)
            metadata = self.extract_metadata(data, options)
            sections = self.extract_structure(data, options)
            
            # Create a human-readable text version
            text_content = [f"PDF Document: {metadata.get('title', 'Untitled')}"]
            
            if "author" in metadata:
                text_content.append(f"Author: {metadata['author']}")
            
            if "subject" in metadata:
                text_content.append(f"Subject: {metadata['subject']}")
            
            if "creation_date" in metadata:
                text_content.append(f"Created: {metadata['creation_date']}")
            
            if "page_count" in metadata:
                text_content.append(f"Pages: {metadata['page_count']}")
            
            text_content.append("\n--- Document Text ---\n")
            text_content.append(text)
            
            return "\n".join(text_content), metadata, sections
            
        except Exception as e:
            logger.error(f"Error processing PDF document: {e}")
            raise ValueError(f"Error processing PDF document: {e}")
