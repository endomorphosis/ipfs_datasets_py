"""
PDF Processing - Extract Text with OCR Support

This example demonstrates how to process PDF files, including both text-based
PDFs and image-based PDFs that require OCR (Optical Character Recognition).

Requirements:
    - pypdf or pymupdf: pip install pypdf pymupdf
    - pytesseract: pip install pytesseract
    - Optional: surya_ocr, easyocr for better OCR

Usage:
    python examples/07_pdf_processing.py
"""

import asyncio
import tempfile
from pathlib import Path


def create_sample_pdf():
    """Create a simple PDF for demonstration."""
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import letter
        
        tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
        tmp_file.close()
        
        # Create PDF
        c = canvas.Canvas(tmp_file.name, pagesize=letter)
        c.drawString(100, 750, "Sample PDF Document")
        c.drawString(100, 730, "This is a text-based PDF created for testing.")
        c.drawString(100, 710, "It contains multiple lines of text.")
        c.drawString(100, 690, "PDF processing can extract this text easily.")
        c.showPage()
        c.save()
        
        return tmp_file.name
    except ImportError:
        print("⚠️  reportlab not installed, using alternative method")
        # Create a minimal PDF manually if reportlab not available
        return None


async def demo_basic_pdf_extraction():
    """Extract text from a text-based PDF."""
    print("\n" + "="*70)
    print("DEMO 1: Basic PDF Text Extraction")
    print("="*70)
    
    try:
        from ipfs_datasets_py.processors.specialized.pdf import PDFProcessor
        
        # Create sample PDF
        print("\n📝 Creating sample PDF...")
        pdf_path = create_sample_pdf()
        
        if not pdf_path:
            print("⚠️  Could not create sample PDF, skipping demo")
            return
        
        # Initialize processor
        print("\n🔍 Initializing PDF processor...")
        processor = PDFProcessor()
        
        # Extract text
        print(f"\n📄 Extracting text from PDF...")
        result = await processor.process(pdf_path)
        
        if result.success:
            print("✅ Extraction successful")
            print(f"   Pages: {result.metadata.get('num_pages', 0)}")
            print(f"   Text length: {len(result.text)} characters")
            print(f"\n   Preview:")
            print(f"   {result.text[:200]}...")
        else:
            print(f"❌ Extraction failed: {result.error}")
        
        # Cleanup
        import os
        os.unlink(pdf_path)
        
    except ImportError as e:
        print(f"\n❌ Missing dependencies: {e}")
        print("   Install with: pip install pypdf pymupdf")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


async def demo_pdf_metadata():
    """Extract PDF metadata."""
    print("\n" + "="*70)
    print("DEMO 2: PDF Metadata Extraction")
    print("="*70)
    
    try:
        from ipfs_datasets_py.processors.specialized.pdf import PDFProcessor
        
        pdf_path = create_sample_pdf()
        if not pdf_path:
            return
        
        processor = PDFProcessor()
        
        print("\n📊 Extracting PDF metadata...")
        result = await processor.process(pdf_path)
        
        if result.success and result.metadata:
            print("✅ Metadata extracted:")
            metadata = result.metadata
            
            # Common metadata fields
            fields = ['title', 'author', 'subject', 'creator', 'producer', 
                     'num_pages', 'creation_date', 'modification_date']
            
            for field in fields:
                if field in metadata:
                    print(f"   {field}: {metadata[field]}")
        
        import os
        os.unlink(pdf_path)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")


async def demo_ocr_processing():
    """Demonstrate OCR processing for image-based PDFs."""
    print("\n" + "="*70)
    print("DEMO 3: OCR Processing")
    print("="*70)
    
    print("\n📷 OCR Example")
    print("   OCR processes image-based PDFs or scanned documents")
    print("   Requires: pytesseract, tesseract-ocr system package")
    
    # Example code (requires actual image PDF)
    """
    try:
        from ipfs_datasets_py.processors.specialized.pdf import PDFProcessor
        
        processor = PDFProcessor(ocr_engine="tesseract")
        
        # Process image-based PDF
        result = await processor.process(
            "scanned_document.pdf",
            use_ocr=True
        )
        
        if result.success:
            print(f"✅ OCR extraction: {len(result.text)} chars")
        
    except Exception as e:
        print(f"❌ OCR error: {e}")
    """
    
    print("\n💡 Available OCR Engines:")
    print("   - tesseract: Fast, good accuracy")
    print("   - easyocr: GPU-accelerated, multi-language")
    print("   - surya_ocr: High accuracy, modern architecture")
    print("   - paddleocr: Good for Asian languages")


async def demo_multi_engine_ocr():
    """Demonstrate multi-engine OCR with fallbacks."""
    print("\n" + "="*70)
    print("DEMO 4: Multi-Engine OCR")
    print("="*70)
    
    print("\n🔧 Multi-Engine OCR Configuration")
    
    print("\n   The PDFProcessor supports multiple OCR engines with fallbacks:")
    
    example_code = '''
from ipfs_datasets_py.processors.specialized.pdf import PDFProcessor

# Configure multiple OCR engines
processor = PDFProcessor(
    ocr_engines=["surya", "tesseract", "easyocr"],  # Try in order
    fallback_on_error=True,                          # Fallback if one fails
    confidence_threshold=0.8                          # Min confidence
)

result = await processor.process("document.pdf", use_ocr=True)
    '''
    
    print(example_code)
    
    print("\n💡 Tips:")
    print("   - surya_ocr: Best quality, slower")
    print("   - tesseract: Fast, good for English")
    print("   - easyocr: Good balance, GPU support")
    print("   - Use fallbacks for reliability")


async def demo_pdf_structure_extraction():
    """Extract PDF structure (headings, paragraphs, etc.)."""
    print("\n" + "="*70)
    print("DEMO 5: PDF Structure Extraction")
    print("="*70)
    
    print("\n📑 Structure Extraction")
    print("   Extract document structure beyond raw text:")
    
    example_code = '''
from ipfs_datasets_py.processors.specialized.pdf import PDFProcessor

processor = PDFProcessor(extract_structure=True)
result = await processor.process("document.pdf")

if result.success:
    # Access structured data
    structure = result.metadata.get('structure', {})
    
    print(f"Headings: {len(structure.get('headings', []))}")
    print(f"Paragraphs: {len(structure.get('paragraphs', []))}")
    print(f"Tables: {len(structure.get('tables', []))}")
    print(f"Images: {len(structure.get('images', []))}")
    '''
    
    print(example_code)


async def demo_batch_pdf_processing():
    """Process multiple PDFs in batch."""
    print("\n" + "="*70)
    print("DEMO 6: Batch PDF Processing")
    print("="*70)
    
    print("\n📚 Batch Processing Example")
    
    example_code = '''
from ipfs_datasets_py.processors.specialized.pdf import PDFProcessor
from ipfs_datasets_py.processors.file_converter import BatchProcessor
from pathlib import Path

# Get all PDFs in directory
pdf_files = list(Path("documents/").glob("*.pdf"))

# Create batch processor
processor = PDFProcessor()
batch = BatchProcessor(max_concurrent=5)

# Process all PDFs
results = await batch.process_batch(
    files=pdf_files,
    processor=processor,
    use_ocr=False  # Set True for image PDFs
)

# Summarize results
successful = sum(1 for r in results if r.success)
print(f"Processed: {len(results)} PDFs")
print(f"Successful: {successful}")
print(f"Failed: {len(results) - successful}")
    '''
    
    print(example_code)


def show_tips():
    """Show tips for PDF processing."""
    print("\n" + "="*70)
    print("TIPS FOR PDF PROCESSING")
    print("="*70)
    
    print("\n1. Choosing OCR Engine:")
    print("   - Text PDFs: No OCR needed, fast extraction")
    print("   - Scanned documents: Use OCR")
    print("   - Mixed PDFs: Auto-detect text/image pages")
    
    print("\n2. OCR Performance:")
    print("   - tesseract: Fastest, good for English")
    print("   - easyocr: GPU acceleration, multi-language")
    print("   - surya: Best quality, slower")
    print("   - Use appropriate DPI (300+ for quality)")
    
    print("\n3. Memory Management:")
    print("   - Large PDFs: Process page-by-page")
    print("   - Batch processing: Limit concurrent jobs")
    print("   - Clear caches between large batches")
    
    print("\n4. Quality Optimization:")
    print("   - Preprocessing: Deskew, denoise images")
    print("   - Language hints: Improve accuracy")
    print("   - Post-processing: Clean extracted text")
    
    print("\n5. Common Issues:")
    print("   - Encrypted PDFs: Decrypt first")
    print("   - Complex layouts: May need manual review")
    print("   - Low-quality scans: Enhance before OCR")
    
    print("\n6. System Requirements:")
    print("   - tesseract: apt install tesseract-ocr")
    print("   - GPU: Improves easyocr/surya performance")
    print("   - Memory: ~2GB per OCR process")
    
    print("\n7. Next Steps:")
    print("   - See 09_batch_processing.py for large-scale processing")
    print("   - See 12_graphrag_basic.py for PDF-based RAG")


async def main():
    """Run all PDF processing demonstrations."""
    print("\n" + "="*70)
    print("IPFS DATASETS PYTHON - PDF PROCESSING")
    print("="*70)
    
    await demo_basic_pdf_extraction()
    await demo_pdf_metadata()
    await demo_ocr_processing()
    await demo_multi_engine_ocr()
    await demo_pdf_structure_extraction()
    await demo_batch_pdf_processing()
    
    show_tips()
    
    print("\n" + "="*70)
    print("✅ PDF PROCESSING EXAMPLES COMPLETE")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
