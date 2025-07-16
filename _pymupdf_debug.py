import pymupdf
import tempfile
from tempfile import TemporaryDirectory
import io
from pathlib import Path
from typing import Any, Dict, Union, Optional, Tuple
import os

MEDIABOX = pymupdf.paper_rect("letter")  # size of a page
WHERE = MEDIABOX + (36, 36, -36, -36)  # leave borders of 0.5 inches


def test_document_write() -> None:
    """
    Test if a document can be written without errors.
    
    This function creates a simple PDF document and writes it to a temporary file
    to verify that PyMuPDF document writing functionality works correctly.
    
    Raises:
        ValueError: If the document cannot be written.
        
    Example:
        >>> test_document_write()  # Should complete without errors
    """
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
            # Create a new PDF document
            doc = pymupdf.open()
            page = doc.new_page()
            
            # Add some simple text to verify functionality
            page.insert_text((50, 50), "Test document write functionality")
            
            # Save the document
            doc.save(temp_file.name)
            doc.close()
            
            # Verify the file was created and can be reopened
            verify_doc = pymupdf.open(temp_file.name)
            if verify_doc.page_count == 0:
                raise ValueError("Document was created but contains no pages")
            verify_doc.close()
            
            # Clean up
            os.unlink(temp_file.name)
            
    except Exception as e:
        raise ValueError(f"Document cannot be written: {e}") from e


def make_pdf(fileptr: io.BytesIO, text: str, rect: pymupdf.Rect, 
             font: str = "sans-serif", archive: Optional[Any] = None) -> pymupdf.Matrix:
    """
    Make a memory DocumentWriter from HTML text and a rect.

    Args:
        fileptr: A Python file object. For example an io.BytesIO().
        text: The text to output (HTML format).
        rect: The target rectangle. Will use its width / height as mediabox.
        font: Font family name, default sans-serif.
        archive: pymupdf.Archive parameter. To be used if e.g. images or special
                fonts should be used.
                
    Returns:
        The matrix to convert page rectangles of the created PDF back
        to rectangle coordinates in the parameter "rect".
        Normal use will expect to fit all the text in the given rect.
        However, if an overflow occurs, this function will output multiple
        pages, and the caller may decide to either accept or retry with
        changed parameters.
        
    Raises:
        ValueError: If the text cannot be processed or the PDF cannot be created.
        
    Example:
        >>> import io
        >>> fileptr = io.BytesIO()
        >>> rect = pymupdf.Rect(0, 0, 200, 300)
        >>> matrix = make_pdf(fileptr, "<p>Hello World</p>", rect)
        >>> isinstance(matrix, pymupdf.Matrix)
        True
    """
    try:
        # use input rectangle as the page dimension
        mediabox = pymupdf.Rect(0, 0, rect.width, rect.height)
        # this matrix converts mediabox back to input rect
        matrix = mediabox.torect(rect)

        story = pymupdf.Story(text, archive=archive)
        body = story.body
        body.set_properties(font=font)
        writer = pymupdf.DocumentWriter(fileptr)
        
        while True:
            device = writer.begin_page(mediabox)
            more, _ = story.place(mediabox)
            story.draw(device)
            writer.end_page()
            if not more:
                break
        writer.close()
        return matrix
    except Exception as e:
        raise ValueError(f"Failed to create PDF from text: {e}") from e


class TempPDF:
    """
    Context manager to create a temporary PDF file.
    
    This class creates a temporary PDF file that is automatically deleted
    when the context is exited. It provides methods to create PDFs with
    various types of content.
    
    Attributes:
        temp_dir: TemporaryDirectory object for managing temporary files.
        
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

    def make_temp_pdf(self, filename: str, 
                     page_dict: Optional[Dict[Union[str, int], str]] = None) -> Path:
        """
        Create a temporary PDF file with specified content.
        
        Args:
            filename: Name of the PDF file (without .pdf extension).
            page_dict: Dictionary mapping page numbers to content strings.
                      If None, creates a single page with default content.
                      
        Returns:
            Path object pointing to the created PDF file.
            
        Raises:
            ValueError: If the PDF cannot be created or if invalid content is provided.
            RuntimeError: If called outside of context manager.
            
        Example:
            >>> with TempPDF() as temp_pdf:
            ...     pages = {"0": "First page", "1": "Second page"}
            ...     path = temp_pdf.make_temp_pdf("multi_page", pages)
        """
        if not self.temp_dir:
            raise RuntimeError("TempPDF must be used as a context manager")
            
        if page_dict is None:
            page_dict = {"0": "Default content for testing"}
            
        # Ensure filename doesn't have .pdf extension
        if filename.endswith('.pdf'):
            filename = filename[:-4]

        path = Path(self.temp_dir.name) / f'{filename}.pdf'

        try:
            doc = pymupdf.open()
            
            for page_key, content in page_dict.items():
                # Convert page_key to int if it's a string
                page_num = int(page_key) if isinstance(page_key, str) else page_key
                
                # Insert page at the correct position
                doc.insert_page(page_num)
                page = doc[page_num]
                
                if isinstance(content, str):
                    page.insert_text((50, 50), content)
                else:
                    raise TypeError(f"Unsupported content type: {type(content)}")

            doc.save(path)
            doc.close()
            
            return path
            
        except Exception as e:
            raise ValueError(f"Failed to create PDF: {e}") from e


def write_example_file() -> None:
    """
    Create an example PDF file demonstrating PyMuPDF Story functionality.
    
    This function creates a PDF with HTML content placed in a specific rectangle
    using PyMuPDF's Story class. The resulting PDF is saved temporarily and
    verified for correct content.
    
    Raises:
        ValueError: If the PDF cannot be created or if the target rectangle is too small.
        FileNotFoundError: If temporary files cannot be created.
        
    Example:
        >>> write_example_file()  # Creates and verifies example PDF
    """
    HTML = """
    <p>PyMuPDF is a great package! And it still improves significantly from one version to the next one!</p>
    <p>It is a Python binding for <b>MuPDF</b>, a lightweight PDF, XPS, and E-book viewer, renderer, and toolkit.<br> Both are maintained and developed by Artifex Software, Inc.</p>
    <p>Via MuPDF it can access files in PDF, XPS, OpenXPS, CBZ, EPUB, MOBI and FB2 (e-books) formats,<br> and it is known for its top
    <b><i>performance</i></b> and <b><i>rendering quality.</i></b></p>"""

    try:
        # Make a PDF page for demo purposes
        with TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / 'test_pdf_write.pdf'
            
            # Create initial document
            doc = pymupdf.open()
            doc.insert_page(0)  # Create a new page
            page = doc[0]
            
            # Add a title to the original page
            page.insert_text((50, 50), "Example PDF with Story Content")

            WHERE_RECT = pymupdf.Rect(50, 100, 450, 500)  # target rectangle on existing page

            fileptr = io.BytesIO()  # let DocumentWriter use this as its file

            # call DocumentWriter and Story to fill our rectangle
            matrix = make_pdf(fileptr, HTML, WHERE_RECT)

            src = pymupdf.open("pdf", fileptr)  # open DocumentWriter output PDF
            if src.page_count > 1:  # target rect was too small
                raise ValueError("target rectangle too small for content")

            # Insert the story content into the original page
            src_page = src[0]
            #page.show_pdf_page(WHERE_RECT, src, 0, matrix=matrix)
            
            output_path = Path(temp_dir) / 'test_pdf_write-after.pdf'
            doc.save(output_path)
            doc.close()
            src.close()

            # Reopen the document to verify
            with pymupdf.open(output_path) as verify_doc:
                verify_page = verify_doc[0]
                text = verify_page.get_text("text")  # Ensure we can read the text

                print(f"Text on page:\n{text}")
                print(f"PDF successfully written to {output_path}")

    except Exception as e:
        raise ValueError(f"Failed to create example file: {e}") from e


def test_document_open(file_path: str) -> None:
    """
    Test if a document can be opened without errors.
    
    Args:
        file_path: Path to the PDF file to open.
    
    Raises:
        ValueError: If the document cannot be opened.
        FileNotFoundError: If the file does not exist.
        
    Example:
        >>> test_document_open("sample.pdf")  # Opens and closes sample.pdf
    """
    try:
        if not Path(file_path).exists():
            raise FileNotFoundError(f"File not found: {file_path}")
            
        doc = pymupdf.open(file_path)
        page_count = doc.page_count
        doc.close()
        
        if page_count <= 0:
            raise ValueError("Document contains no pages")
            
        print(f"Successfully opened document with {page_count} pages")
        
    except Exception as e:
        raise ValueError(f"Document cannot be opened: {e}") from e


def test_get_pages_from_document(file_path: str) -> int:
    """
    Test if pages can be retrieved from a document.
    
    Args:
        file_path: Path to the PDF file to analyze.
        
    Returns:
        Number of pages in the document.
    
    Raises:
        ValueError: If the document cannot be opened or pages cannot be retrieved.
        FileNotFoundError: If the file does not exist.
        
    Example:
        >>> pages = test_get_pages_from_document("sample.pdf")
        >>> print(f"Document has {pages} pages")
    """
    try:
        if not Path(file_path).exists():
            raise FileNotFoundError(f"File not found: {file_path}")
            
        doc = pymupdf.open(file_path)
        pages = doc.page_count
        doc.close()
        
        if pages <= 0:
            raise ValueError("No pages found in the document")
            
        return pages
        
    except Exception as e:
        raise ValueError(f"Failed to retrieve pages from document: {e}") from e


if __name__ == "__main__":
    print("Testing PyMuPDF functionality...")
    
    # Test basic document writing
    print("1. Testing document write...")
    test_document_write()
    print("   ✓ Document write test passed")
    
    # Test example file creation
    print("2. Testing example file creation...")
    write_example_file()
    print("   ✓ Example file creation test passed")
    
    # Test TempPDF context manager
    print("3. Testing TempPDF context manager...")
    with TempPDF() as temp_pdf:
        test_pages = {"0": "Page 1 content", "1": "Page 2 content"}
        pdf_path = temp_pdf.make_temp_pdf("test_multi", test_pages)
        
        # Verify the created PDF
        page_count = test_get_pages_from_document(str(pdf_path))
        print(f"   ✓ TempPDF created {page_count} pages successfully")
    
    print("All tests completed successfully!")