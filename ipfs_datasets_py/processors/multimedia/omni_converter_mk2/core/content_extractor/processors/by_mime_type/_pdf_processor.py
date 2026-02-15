# """
# PDF processor implementation using PyPDF2.

# This module provides a concrete implementation of DocumentProcessor for PDF files
# using the PyPDF2 library.

# # TODO Redo this so that it removes inheritance.
# """

# import io
# import re
# from typing import Any, Optional, BinaryIO
# from datetime import datetime

# from core.content_extractor.processors.document_processor import DocumentProcessor
# from logger import logger


# class PyPDF2Processor(DocumentProcessor):
#     """
#     PDF processor implementation using PyPDF2.
    
#     This class provides functionality to extract text, metadata, and structure
#     from PDF files using the PyPDF2 library.
#     """
    
#     def __init__(self):
#         """Initialize the PDF processor."""
#         self._supported_formats = ["pdf"]
    
#     def can_process(self, format_name: str) -> bool:
#         """
#         Check if this processor can handle the given format.
        
#         Args:
#             format_name: The name of the format to check.
            
#         Returns:
#             True if this processor can handle the format and PyPDF2 is available,
#             False otherwise.
#         """
#         return PYPDF2_AVAILABLE and format_name.lower() in self.supported_formats
    
#     @property
#     def supported_formats(self) -> list[str]:
#         """
#         Get the list of formats supported by this processor.
        
#         Returns:
#             A list of format names supported by this processor.
#         """
#         return self._supported_formats if PYPDF2_AVAILABLE else []
    
#     def get_processor_info(self) -> dict[str, Any]:
#         """
#         Get information about this processor.
        
#         Returns:
#             A dictionary containing information about this processor.
#         """
#         info = {
#             "name": "PyPDF2Processor",
#             "supported_formats": self.supported_formats,
#             "available": PYPDF2_AVAILABLE
#         }
        
#         if PYPDF2_AVAILABLE:
#             info["version"] = PyPDF2.__version__
        
#         return info
    
#     def extract_text(self, data: bytes, options: dict[str, Any]) -> str:
#         """
#         Extract plain text from a PDF document.
        
#         Args:
#             data: The binary data of the PDF document.
#             options: Processing options.
            
#         Returns:
#             Extracted text from the PDF document.
            
#         Raises:
#             ValueError: If PyPDF2 is not available or the data cannot be processed as a PDF.
#         """
        
#         try:
#             # Create a file-like object from the bytes
#             pdf_file = io.BytesIO(data)
            
#             # Open the PDF file
#             reader = PyPDF2.PdfReader(pdf_file)
            
#             # Extract text from each page
#             text_parts = []
            
#             for page_num, page in enumerate(reader.pages):
#                 # Extract text from the page
#                 text = page.extract_text()
                
#                 # Add page number and text
#                 if text:
#                     text_parts.append(f"--- Page {page_num + 1} ---")
#                     text_parts.append(text)
            
#             # Join all text parts
#             return "\n\n".join(text_parts)
            
#         except Exception as e:
#             logger.error(f"Error extracting text from PDF: {e}")
#             raise ValueError(f"Error extracting text from PDF: {e}")
    
#     def extract_metadata(self, data: bytes, options: dict[str, Any]) -> dict[str, Any]:
#         """
#         Extract metadata from a PDF document.
        
#         Args:
#             data: The binary data of the PDF document.
#             options: Processing options.
            
#         Returns:
#             Metadata extracted from the PDF document.
            
#         Raises:
#             ValueError: If PyPDF2 is not available or the data cannot be processed as a PDF.
#         """
        
#         try:
#             # Create a file-like object from the bytes
#             pdf_file = io.BytesIO(data)
            
#             # Open the PDF file
#             reader = PyPDF2.PdfReader(pdf_file)
            
#             # Extract document info
#             metadata = {}
            
#             # Get basic information
#             metadata["page_count"] = len(reader.pages)
#             metadata["is_encrypted"] = reader.is_encrypted
            
#             # Extract document information dictionary if available
#             if hasattr(reader, "metadata") and reader.metadata:
#                 doc_info = reader.metadata
                
#                 # Map common metadata fields
#                 field_mapping = {
#                     "/Title": "title",
#                     "/Author": "author",
#                     "/Subject": "subject",
#                     "/Keywords": "keywords",
#                     "/Creator": "creator",
#                     "/Producer": "producer",
#                     "/CreationDate": "creation_date",
#                     "/ModDate": "modification_date"
#                 }
                
#                 for key, new_key in field_mapping.items():
#                     if key in doc_info:
#                         value = doc_info[key]
#                         # Convert PDF date strings to ISO format if possible
#                         if key in ["/CreationDate", "/ModDate"] and value:
#                             date_str = str(value)
#                             # Handle common PDF date format: D:YYYYMMDDHHmmSS
#                             date_match = re.match(r'D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})', date_str)
#                             if date_match:
#                                 try:
#                                     year, month, day, hour, minute, second = map(int, date_match.groups())
#                                     dt = datetime(year, month, day, hour, minute, second)
#                                     value = dt.isoformat()
#                                 except (ValueError, OverflowError):
#                                     # If date parsing fails, keep the original string
#                                     pass
#                         metadata[new_key] = value
            
#             # Extract file size
#             metadata["file_size_bytes"] = len(data)
            
#             # Extract PDF version if available
#             if hasattr(reader, "pdf_header"):
#                 metadata["pdf_version"] = reader.pdf_header
            
#             return metadata
            
#         except Exception as e:
#             logger.error(f"Error extracting metadata from PDF: {e}")
#             raise ValueError(f"Error extracting metadata from PDF: {e}")
    
#     def extract_structure(self, data: bytes, options: dict[str, Any]) -> list[dict[str, Any]]:
#         """
#         Extract structural elements from a PDF document.
        
#         Args:
#             data: The binary data of the PDF document.
#             options: Processing options.
            
#         Returns:
#             A list of structural elements extracted from the PDF document.
            
#         Raises:
#             ValueError: If PyPDF2 is not available or the data cannot be processed as a PDF.
#         """
#         try:
#             # Create a file-like object from the bytes
#             pdf_file = io.BytesIO(data)
            
#             # Open the PDF file
#             reader = PyPDF2.PdfReader(pdf_file)
            
#             # Extract structure
#             structure = []
            
#             # Add document as a section
#             structure.append({
#                 "type": "document",
#                 "content": "PDF Document"
#             })
            
#             # Add one section per page
#             for page_num, page in enumerate(reader.pages):
#                 # Extract text from the page
#                 text = page.extract_text()
                
#                 # Add page section
#                 structure.append({
#                     "type": "page",
#                     "page_number": page_num + 1,
#                     "content": text[:1000] + ("..." if len(text) > 1000 else "")
#                 })
                
#                 # Get page dimensions
#                 if "/MediaBox" in page:
#                     media_box = page["/MediaBox"]
#                     if isinstance(media_box, list) and len(media_box) >= 4:
#                         structure.append({
#                             "type": "dimensions",
#                             "page_number": page_num + 1,
#                             "width": float(media_box[2]),
#                             "height": float(media_box[3])
#                         })
            
#             # Extract outline/bookmarks if available
#             if reader.outline:
#                 self._extract_outline(reader.outline, structure)
            
#             return structure
            
#         except Exception as e:
#             logger.error(f"Error extracting structure from PDF: {e}")
#             raise ValueError(f"Error extracting structure from PDF: {e}")
    
#     def _extract_outline(self, outline, structure, level=0):
#         """Helper method to extract outline/bookmarks from the PDF."""
#         if not outline:
#             return
        
#         if isinstance(outline, list):
#             for item in outline:
#                 self._extract_outline(item, structure, level)
#         else:
#             # Add outline item to structure
#             if hasattr(outline, '/Title') and hasattr(outline, '/Page'):
#                 structure.append({
#                     "type": "bookmark",
#                     "level": level,
#                     "title": outline['/Title'],
#                     "page": outline['/Page']
#                 })
            
#             # Process any children
#             if hasattr(outline, '/Count') and outline['/Count'] > 0 and hasattr(outline, '/Kids'):
#                 self._extract_outline(outline['/Kids'], structure, level + 1)
    
#     def process_document(self, data: bytes, options: dict[str, Any]) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
#         """
#         Process a PDF document completely, extracting text, metadata, and structure.
        
#         Args:
#             data: The binary data of the PDF document.
#             options: Processing options.
            
#         Returns:
#             A tuple of (text content, metadata, sections).
            
#         Raises:
#             ValueError: If PyPDF2 is not available or the data cannot be processed as a PDF.
#         """
        
#         try:
#             # Extract text, metadata, and structure
#             text = self.extract_text(data, options)
#             metadata = self.extract_metadata(data, options)
#             sections = self.extract_structure(data, options)
            
#             # Create a human-readable text version
#             text_content = [f"PDF Document: {metadata.get('title', 'Untitled')}"]
            
#             if "author" in metadata:
#                 text_content.append(f"Author: {metadata['author']}")
            
#             if "subject" in metadata:
#                 text_content.append(f"Subject: {metadata['subject']}")
            
#             if "creation_date" in metadata:
#                 text_content.append(f"Created: {metadata['creation_date']}")
            
#             if "page_count" in metadata:
#                 text_content.append(f"Pages: {metadata['page_count']}")
            
#             text_content.append("\n--- Document Text ---\n")
#             text_content.append(text)
            
#             return "\n".join(text_content), metadata, sections
            
#         except Exception as e:
#             logger.error(f"Error processing PDF document: {e}")
#             raise ValueError(f"Error processing PDF document: {e}")





# class PDFProcessor:
#     """
#     A class to handle PDF processing using PyPDF2.

#     This class provides methods to extract text, metadata, and structure from PDF files.
#     """
    
#     from types_ import Configs

#     def __init__(self,
#                  resources: dict[str, Any] = None,
#                  configs: Configs = None
#                  ):
#         """Initialize the PDF processor."""
#         self.configs = configs
#         self.resources = resources
    
#         self.ocr_processor = self.resources['ocr_processor']
