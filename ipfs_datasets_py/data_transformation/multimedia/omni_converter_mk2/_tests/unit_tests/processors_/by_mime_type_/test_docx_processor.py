# """
# Tests for the DOCX processor implementation.

# This module contains tests for the DocxProcessor class, covering text extraction, 
# metadata extraction, structure extraction, and error handling.
# """

# import os
# import unittest
# from unittest.mock import MagicMock, patch
# import tempfile
# from io import BytesIO

# # Import the processor to test
# from core.content_extractor.processors.python_docx_processor import DocxProcessor, PYTHON_DOCX_AVAILABLE

# # Create a sample DOCX for testing
# SAMPLE_DOCX_DATA = None  # This will be populated in setUpModule if python-docx is available

# def setUpModule():
#     """Set up the module level fixtures."""
#     global SAMPLE_DOCX_DATA
    
#     # Skip creating test data if python-docx is not available
#     if not PYTHON_DOCX_AVAILABLE:
#         return
    
#     # Create a simple test DOCX document
#     try:
#         import docx
        
#         # Create a new document
#         doc = docx.Document()
        
#         # Add a title
#         doc.add_heading('DOCX Test Document', 0)
        
#         # Add some paragraphs
#         doc.add_paragraph('This is a test document for the DOCX processor.')
        
#         doc.add_heading('Section 1', level=1)
#         doc.add_paragraph('This is content in section 1. It contains some text to test extraction.')
        
#         doc.add_heading('Section 2', level=1)
#         p = doc.add_paragraph('This section has a ')
#         p.add_run('bold').bold = True
#         p.add_run(' word and an ')
#         p.add_run('italic').italic = True
#         p.add_run(' word.')
        
#         # Add a table
#         table = doc.add_table(rows=2, cols=2)
#         cell = table.cell(0, 0)
#         cell.text = 'Cell 1'
#         cell = table.cell(0, 1)
#         cell.text = 'Cell 2'
#         cell = table.cell(1, 0)
#         cell.text = 'Cell 3'
#         cell = table.cell(1, 1)
#         cell.text = 'Cell 4'
        
#         # Save the document to a buffer
#         buffer = BytesIO()
#         doc.save(buffer)
#         buffer.seek(0)
        
#         # Get the DOCX data
#         SAMPLE_DOCX_DATA = buffer.getvalue()
    
#     except ImportError:
#         # If python-docx is not available, we can't create a test document
#         SAMPLE_DOCX_DATA = None


# @unittest.skipIf(not PYTHON_DOCX_AVAILABLE, "python-docx not available")
# class TestDocxProcessor(unittest.TestCase):
#     """Test the DocxProcessor class."""
    
#     def setUp(self):
#         """Set up test fixtures."""
#         self.processor = DocxProcessor()
        
#         # Check if we have test data
#         if SAMPLE_DOCX_DATA is None:
#             self.skipTest("Could not create test DOCX data")
        
#         # Create a temporary test file if needed for specific tests
#         self.test_file = None
    
#     def tearDown(self):
#         """Tear down test fixtures."""
#         # Remove temporary file if it was created
#         if self.test_file and os.path.exists(self.test_file):
#             try:
#                 os.unlink(self.test_file)
#             except:
#                 pass
    
#     def test_initialization(self):
#         """Test that the processor is initialized correctly."""
#         self.assertIn("docx", self.processor.supported_formats)
#         self.assertIsInstance(self.processor, DocxProcessor)
    
#     def test_can_process(self):
#         """Test the can_process method."""
#         self.assertTrue(self.processor.can_process("docx"))
#         self.assertTrue(self.processor.can_process("DOCX"))
#         self.assertFalse(self.processor.can_process("doc"))
#         self.assertFalse(self.processor.can_process(""))
    
#     def test_get_supported_formats(self):
#         """Test the supported_formats method."""
#         formats = self.processor.supported_formats
#         self.assertIn("docx", formats)
    
#     def test_get_processor_info(self):
#         """Test the get_processor_info method."""
#         info = self.processor.get_processor_info()
#         self.assertEqual(info["name"], "DocxProcessor")
#         self.assertTrue(info["available"])
#         self.assertIn("supported_formats", info)
#         self.assertIn("docx", info["supported_formats"])
    
#     def test_extract_text(self):
#         """Test extracting text from a DOCX document."""
#         # Test with sample DOCX data
#         text = self.processor.extract_text(SAMPLE_DOCX_DATA, {})
        
#         # Check that the text contains expected content
#         self.assertIn("DOCX Test Document", text)
#         self.assertIn("Section 1", text)
#         self.assertIn("This is content in section 1", text)
    
#     def test_extract_metadata(self):
#         """Test extracting metadata from a DOCX document."""
#         # Test with sample DOCX data
#         metadata = self.processor.extract_metadata(SAMPLE_DOCX_DATA, {})
        
#         # Check that metadata contains expected fields
#         self.assertIn("file_size_bytes", metadata)
#         self.assertIn("paragraph_count", metadata)
#         self.assertIn("table_count", metadata)
#         self.assertEqual(metadata["table_count"], 1)  # We added one table
#         self.assertIn("statistics", metadata)
#         self.assertIn("word_count", metadata["statistics"])
    
#     def test_extract_structure(self):
#         """Test extracting structure from a DOCX document."""
#         # Test with sample DOCX data
#         structure = self.processor.extract_structure(SAMPLE_DOCX_DATA, {})
        
#         # Check we have structure elements
#         self.assertGreater(len(structure), 0)
        
#         # Check for document section
#         doc_sections = [s for s in structure if s["type"] == "document"]
#         self.assertEqual(len(doc_sections), 1)
        
#         # Check for table
#         table_sections = [s for s in structure if s["type"] == "table"]
#         self.assertEqual(len(table_sections), 1)
#         if table_sections:
#             self.assertEqual(table_sections[0]["rows"], 2)
#             self.assertEqual(table_sections[0]["columns"], 2)
    
#     def test_process_document(self):
#         """Test processing a complete DOCX document."""
#         # Test with sample DOCX data
#         text, metadata, sections = self.processor.process_document(SAMPLE_DOCX_DATA, {})
        
#         # Check results
#         self.assertIsInstance(text, str)
#         self.assertIsInstance(metadata, dict)
#         self.assertIsInstance(sections, list)
        
#         # Check that the text includes expected content
#         self.assertIn("DOCX Document:", text)
#         self.assertIn("DOCX Test Document", text)
#         self.assertIn("Section 1", text)
        
#         # Check that sections have expected types
#         section_types = set(s["type"] for s in sections)
#         self.assertIn("document", section_types)
#         self.assertIn("table", section_types)
    
#     def test_invalid_docx(self):
#         """Test handling of invalid DOCX data."""
#         # Create some invalid DOCX data
#         invalid_data = b"This is not a DOCX file"
        
#         # Test all methods with invalid data and verify they raise ValueError
#         with self.assertRaises(ValueError):
#             self.processor.extract_text(invalid_data, {})
        
#         with self.assertRaises(ValueError):
#             self.processor.extract_metadata(invalid_data, {})
        
#         with self.assertRaises(ValueError):
#             self.processor.extract_structure(invalid_data, {})
        
#         with self.assertRaises(ValueError):
#             self.processor.process_document(invalid_data, {})
    
#     @patch('format_handlers.processors.docx_processor.PYTHON_DOCX_AVAILABLE', False)
#     def test_unavailable(self):
#         """Test behavior when python-docx is not available."""
#         # Create a processor with PYTHON_DOCX_AVAILABLE patched to False
#         processor = DocxProcessor()
        
#         # Check that it correctly reports no supported formats
#         self.assertEqual(processor.supported_formats, [])
#         self.assertFalse(processor.can_process("docx"))
        
#         # Check that all methods raise ValueError
#         with self.assertRaises(ValueError):
#             processor.extract_text(SAMPLE_DOCX_DATA, {})
        
#         with self.assertRaises(ValueError):
#             processor.extract_metadata(SAMPLE_DOCX_DATA, {})
        
#         with self.assertRaises(ValueError):
#             processor.extract_structure(SAMPLE_DOCX_DATA, {})
        
#         with self.assertRaises(ValueError):
#             processor.process_document(SAMPLE_DOCX_DATA, {})


# if __name__ == "__main__":
#     unittest.main()