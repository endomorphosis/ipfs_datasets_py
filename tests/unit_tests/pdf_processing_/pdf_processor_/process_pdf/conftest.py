from typing import Dict, List, Optional, Union, Any
from datetime import datetime
from pathlib import Path
import io
import tempfile

try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter, A4, legal
    from reportlab.lib.colors import black, red, blue, green
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.lib.units import inch
except ImportError:
    raise ImportError("reportlab is required. Install with: pip install reportlab")

try:
    from PIL import Image as PILImage, ImageDraw, ImageFont
except ImportError:
    raise ImportError("Pillow is required. Install with: pip install Pillow")


class PDFTestGenerator:
    """
    Comprehensive PDF test file generator for testing PDF conversion functionality.
    
    Creates PDFs with various characteristics including different content types,
    formatting, metadata, and structural complexity to thoroughly test PDF
    conversion classes.
    """
    
    def __init__(self, output_dir: Optional[Union[str, Path]] = None):
        """
        Initialize PDF test generator.
        
        Args:
            output_dir: Directory to save generated PDFs. Defaults to current directory.
        """
        self.output_dir = Path(output_dir) if output_dir else Path.cwd()
        self.output_dir.mkdir(exist_ok=True)

    def generate_multipage_pdf(
        self,
        filepath: str = "multipage.pdf",
        content_per_page: List[str] = ["This is some sample text for page 1.",],
        **metadata
    ) -> Path:
        """
        Generate a multi-page PDF with varying content.

        Args:
            filename: Name of the output PDF file
            page_count: Number of pages to generate
            content_per_page: List of content for each page. If None, generates default content.
            **metadata: Additional metadata
            
        Returns:
            Path to the generated PDF file
            
        Raises:
            OSError: If file cannot be written
            ValueError: If page_count is less than 1
        """
        if not Path(filepath).is_dir():
            raise IsADirectoryError(f"Expected a file path, but got: {filepath}")

        if not isinstance(content_per_page, list):
            raise TypeError(f"content_per_page must be a list, got {type(content_per_page).__name__}")

        for idx, content in enumerate(content_per_page, start=1):
            if not isinstance(content, str):
                raise TypeError(
                    f"Each content item must be a string, got {type(content).__name__} for item {idx}"
                )

        page_count = len(content_per_page)

        c = canvas.Canvas(str(filepath), pagesize=letter)

        # Set metadata
        if metadata:
            for key, value in metadata.items():
                setattr(c, key.lower(), value)
        
        for idx in range(page_count):
            content = content_per_page[idx]

            c.drawString(100, 750, content)
            c.drawString(100, 730, f"Page {idx + 1}")
            
            if idx < page_count - 1:
                c.showPage()

        c.save()
        return filepath

    def generate_pdf_with_table():
        pass

    def generate_formatted_pdf(
        self,
        filename: str = "formatted.pdf",
        **metadata
    ) -> Path:
        """
        Generate a PDF with various text formatting (fonts, sizes, colors).
        
        Args:
            filename: Name of the output PDF file
            **metadata: Additional metadata
            
        Returns:
            Path to the generated PDF file
            
        Raises:
            OSError: If file cannot be written
        """
        filepath = self.output_dir / filename
        
        c = canvas.Canvas(str(filepath), pagesize=letter)
        
        # Set metadata
        if metadata:
            for key, value in metadata.items():
                setattr(c, key.lower(), value)
        
        # Different fonts and sizes
        y_position = 750
        
        c.setFont("Helvetica", 24)
        c.drawString(100, y_position, "Large Helvetica Title")
        y_position -= 40
        
        c.setFont("Times-Roman", 12)
        c.drawString(100, y_position, "Times Roman body text")
        y_position -= 20
        
        c.setFont("Courier", 10)
        c.drawString(100, y_position, "Courier monospace text")
        y_position -= 20
        
        # Colors
        c.setFillColor(red)
        c.drawString(100, y_position, "Red text")
        y_position -= 20
        
        c.setFillColor(blue)
        c.drawString(100, y_position, "Blue text")
        y_position -= 20
        
        c.setFillColor(green)
        c.drawString(100, y_position, "Green text")
        
        c.save()
        return filepath
    
    def _create_text_image(
        self,
        text: str,
        width: int = 400,
        height: int = 200,
        background_color: str = "white",
        text_color: str = "black",
        font_size: int = 20
    ) -> io.BytesIO:
        """
        Create an image with text using PIL.
        
        Args:
            text: Text to render on the image
            width: Image width in pixels
            height: Image height in pixels
            background_color: Background color name or hex
            text_color: Text color name or hex
            font_size: Font size for the text
            
        Returns:
            BytesIO object containing the PNG image data
        """
        # Create image
        img = PILImage.new('RGB', (width, height), background_color)
        draw = ImageDraw.Draw(img)

        # Try to use a better font, fall back to default
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except Exception as e:
            raise RuntimeError(f"Could not get Arial font: {e}.") from e

        # Calculate text position (centered)
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (width - text_width) // 2
        y = (height - text_height) // 2
        
        # Draw text
        draw.text((x, y), text, fill=text_color, font=font)

        # Save to BytesIO
        img_buffer = io.BytesIO()
        img.save(img_buffer, format='PNG')
        img_buffer.seek(0)

        return img_buffer

    def generate_complex_pdf(
        self,
        filename: str = "complex.pdf",
        include_table: bool = True,
        include_shapes: bool = True,
        **metadata
    ) -> Path:
        """
        Generate a complex PDF with tables, shapes, and mixed content.
        
        Args:
            filename: Name of the output PDF file
            include_table: Whether to include a table
            include_shapes: Whether to include geometric shapes
            **metadata: Additional metadata
            
        Returns:
            Path to the generated PDF file
            
        Raises:
            OSError: If file cannot be written
        """
        filepath = self.output_dir / filename
        
        doc = SimpleDocTemplate(str(filepath), pagesize=letter)
        story = []
        styles = getSampleStyleSheet()
        
        # Add title
        title = Paragraph("Complex PDF Test Document", styles['Title'])
        story.append(title)
        story.append(Spacer(1, 12))
        
        # Add paragraphs
        content = """
        This is a complex PDF document designed to test comprehensive PDF conversion.
        It contains multiple elements including formatted text, tables, and various
        structural components that a robust PDF converter should handle correctly.
        """
        para = Paragraph(content, styles['Normal'])
        story.append(para)
        story.append(Spacer(1, 12))
        
        # Add table if requested
        if include_table:
            data = [
                ['Header 1', 'Header 2', 'Header 3'],
                ['Row 1 Col 1', 'Row 1 Col 2', 'Row 1 Col 3'],
                ['Row 2 Col 1', 'Row 2 Col 2', 'Row 2 Col 3'],
                ['Row 3 Col 1', 'Row 3 Col 2', 'Row 3 Col 3'],
            ]
            
            table = Table(data)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), blue),
                ('TEXTCOLOR', (0, 0), (-1, 0), black),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 14),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), '#f0f0f0'),
                ('GRID', (0, 0), (-1, -1), 1, black)
            ]))
            
            story.append(table)
            story.append(Spacer(1, 12))
        
        # Set metadata
        if metadata:
            doc.title = metadata.get('title', 'Complex Test PDF')
            doc.author = metadata.get('author', 'PDF Test Generator')
            doc.subject = metadata.get('subject', 'PDF Conversion Testing')
        
        doc.build(story)
        return filepath
    
    def generate_metadata_rich_pdf(
        self,
        filename: str = "metadata_rich.pdf",
        title: str = "Test PDF with Rich Metadata",
        author: str = "Test Author",
        subject: str = "PDF Testing",
        keywords: str = "test,pdf,conversion,metadata",
        creator: str = "PDF Test Generator",
        content: str = "This PDF contains comprehensive metadata for testing."
    ) -> Path:
        """
        Generate a PDF with comprehensive metadata.
        
        Args:
            filename: Name of the output PDF file
            title: PDF title metadata
            author: PDF author metadata
            subject: PDF subject metadata
            keywords: PDF keywords metadata
            creator: PDF creator metadata
            content: Text content of the PDF
            
        Returns:
            Path to the generated PDF file
            
        Raises:
            OSError: If file cannot be written
        """
        filepath = self.output_dir / filename

        c = canvas.Canvas(str(filepath), pagesize=letter)

        c.drawString(100, 750, f"Title: {title}")
        c.drawString(100, 730, f"Author: {author}")
        c.drawString(100, 710, f"Subject: {subject}")
        c.drawString(100, 690, f"Keywords: {keywords}")
        c.drawString(100, 650, content)
        
        c.save()
        return filepath
    
    def generate_test_suite(
        self,
        suite_name: str = "pdf_test_suite"
    ) -> Dict[str, Path]:
        """
        Generate a complete suite of test PDFs with various characteristics.
        
        Args:
            suite_name: Base name for the test suite directory
            
        Returns:
            Dictionary mapping test case names to generated file paths
            
        Raises:
            OSError: If files cannot be written
        """
        suite_dir = self.output_dir / suite_name
        suite_dir.mkdir(exist_ok=True)
        
        original_output_dir = self.output_dir
        self.output_dir = suite_dir
        
        try:
            test_files = {}
            
            # Simple text PDF
            test_files['simple'] = self.generate_simple_text_pdf(
                "01_simple.pdf",
                "Simple text content for basic testing."
            )
            
            # Multi-page PDF
            test_files['multipage'] = self.generate_multipage_pdf(
                "02_multipage.pdf",
                page_count=3,
                content_per_page=[
                    "First page content",
                    "Second page with different text",
                    "Third and final page"
                ]
            )
            
            # Formatted PDF
            test_files['formatted'] = self.generate_formatted_pdf(
                "03_formatted.pdf"
            )
            
            # Complex PDF
            test_files['complex'] = self.generate_complex_pdf(
                "04_complex.pdf",
                include_table=True,
                include_shapes=True
            )
            
            # Metadata-rich PDF
            test_files['metadata'] = self.generate_metadata_rich_pdf(
                "05_metadata.pdf",
                title="Comprehensive Test Document",
                author="Automated Test Generator",
                subject="PDF Conversion Testing Suite",
                keywords="test,automation,pdf,conversion,metadata,comprehensive"
            )
            
            # Empty PDF
            test_files['empty'] = self.generate_simple_text_pdf(
                "06_empty.pdf",
                ""
            )
            
            # Large text PDF
            large_content = "This is a test sentence. " * 1000
            test_files['large'] = self.generate_simple_text_pdf(
                "07_large.pdf",
                large_content
            )
            
            return test_files
            
        finally:
            self.output_dir = original_output_dir


def create_pdf_test_files(
    output_directory: Optional[Union[str, Path]] = None,
    generate_suite: bool = True
) -> Union[Dict[str, Path], PDFTestGenerator]:
    """
    Convenience function to create PDF test files.
    
    Args:
        output_directory: Directory to save generated PDFs
        generate_suite: If True, generates a complete test suite
        
    Returns:
        If generate_suite is True, returns dict of test case names to file paths.
        Otherwise, returns PDFTestGenerator instance for custom generation.
        
    Example:
        # Generate complete test suite
        test_files = create_pdf_test_files()
        
        # Generate custom PDFs
        generator = create_pdf_test_files(generate_suite=False)
        custom_pdf = generator.generate_simple_text_pdf("custom.pdf", "Custom content")
    """
    generator = PDFTestGenerator(output_directory)
    
    if generate_suite:
        return generator.generate_test_suite()
    else:
        return generator


