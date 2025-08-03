import pymupdf
from tempfile import TemporaryDirectory
from pathlib import Path
from typing import Any, Dict, Union, Optional


MEDIABOX = pymupdf.paper_rect("letter")  # size of a page
WHERE = MEDIABOX + (36, 36, -36, -36)  # leave borders of 0.5 inches


class TempPDF:
    """
    Context manager to create a temporary PDF file.
    
    This class creates a temporary PDF file that is automatically deleted
    when the context is exited. It provides methods to create PDFs with
    various types of content.
    
    Attributes:
        temp_dir: TemporaryDirectory object for managing temporary files.

    Methods:
        __enter__: Enter the context and create a temporary directory.
        __exit__: Exit the context and clean up the temporary directory.
        make_temp_pdf: Create a temporary PDF file with specified content.
        
    Example:
        >>> with TempPDF() as temp_pdf:
        ...     path = temp_pdf.make_temp_pdf("test", {"0": "Hello World"})
        ...     print(f"Created PDF at: {path}")
    """
    
    def __init__(self) -> None:
        """Initialize the TempPDF context manager."""
        self.temp_dir: Optional[TemporaryDirectory] = None

    def __enter__(self) -> 'TempPDF':
        """Enter the context and create temporary directory."""
        self.temp_dir = TemporaryDirectory()
        return self

    def __exit__(self, exc_type: Optional[type], exc_value: Optional[Exception], 
                 traceback: Optional[Any]) -> None:
        """Exit the context and cleanup temporary directory."""
        if self.temp_dir:
            self.temp_dir.cleanup()

    def make_temp_pdf(self, 
                     filename: str, 
                     page_dict: Optional[dict[int, str]] = None
                     ) -> Path:
        """
        Create a temporary PDF file with specified content.
        
        Args:
            filename: Name of the PDF file (without .pdf extension).
            page_dict: Dictionary mapping page numbers to content strings.
                      If None, creates a single page with default content.
                      
        Returns:
            Path object pointing to the created PDF file.
            
        Raises:
            TypeError: If page_dict is not a dictionary or contains invalid types for its keys and values.
            ValueError: If the PDF cannot be created.
            RuntimeError: If called outside of context manager.
            
        Example:
            >>> with TempPDF() as temp_pdf:
            ...     pages = {"0": "First page", "1": "Second page"}
            ...     path = temp_pdf.make_temp_pdf("multi_page", pages)
        """
        if not self.temp_dir:
            raise RuntimeError("TempPDF must be used as a context manager")
            
        if page_dict is None:
            page_dict = {0: "Default content for testing"}
            
        # Ensure filename doesn't have .pdf extension
        if filename.endswith('.pdf'):
            filename = filename[:-4]

        path = Path(self.temp_dir.name) / f'{filename}.pdf'

        try:
            doc = pymupdf.open()
            
            for page_num, content in page_dict.items():
                # Validate page_num is an integer.
                if not isinstance(page_num, int):
                    raise TypeError(f"Page number must be an integer, got {type(page_num).__name__}")

                # Insert page at the correct position
                doc.insert_page(page_num)
                page = doc[page_num]
                
                match content:
                    case str():
                        page.insert_text((50, 50), content)
                    case _:
                        raise TypeError(f"Unsupported content type: {type(content)}")

            doc.save(path)
            doc.close()
            return path
            
        except Exception as e:
            raise ValueError(f"Failed to create PDF: {e}") from e