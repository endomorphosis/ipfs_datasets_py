# """
# Test for the XLSX processor implementation.

# This module tests the functionality of the XLSX processor using openpyxl.
# """

# import os
# import io
# import unittest
# from unittest.mock import patch, MagicMock

# from deprecated.processors.xlsx_processor import XlsxProcessor, OPENPYXL_AVAILABLE
# from core.content_extractor.processors.document_processor import DocumentProcessor

# # Skip these tests if openpyxl is not available
# @unittest.skipIf(not OPENPYXL_AVAILABLE, "openpyxl is not available")
# class TestXlsxProcessor(unittest.TestCase):
#     """Test the XLSX processor implementation."""
    
#     def setUp(self):
#         """Set up the test environment."""
#         self.processor = XlsxProcessor()
#         self.test_options = {
#             'include_empty_cells': True,
#             'max_rows': 100
#         }
        
#         # Create a simple mock XLSX file in memory
#         if OPENPYXL_AVAILABLE:
#             import openpyxl
#             # Create a new workbook
#             self.wb = openpyxl.Workbook()
#             # Get the active sheet
#             self.ws = self.wb.active
#             self.ws.title = "Test Sheet"
            
#             # Add some data
#             self.ws['A1'] = "ID"
#             self.ws['B1'] = "Name"
#             self.ws['C1'] = "Value"
            
#             self.ws['A2'] = 1
#             self.ws['B2'] = "Item 1"
#             self.ws['C2'] = 100.5
            
#             self.ws['A3'] = 2
#             self.ws['B3'] = "Item 2"
#             self.ws['C3'] = 200.75
            
#             # Save to a BytesIO object
#             self.xlsx_data = io.BytesIO()
#             self.wb.save(self.xlsx_data)
#             self.xlsx_bytes = self.xlsx_data.getvalue()
            
#             # Add a second sheet
#             self.ws2 = self.wb.create_sheet("Second Sheet")
#             self.ws2['A1'] = "Another sheet"
#             self.ws2['A2'] = "with some data"
            
#             # Save again
#             self.xlsx_data = io.BytesIO()
#             self.wb.save(self.xlsx_data)
#             self.xlsx_bytes_multi = self.xlsx_data.getvalue()
    
#     def test_can_process(self):
#         """Test the can_process method."""
#         self.assertTrue(self.processor.can_process("xlsx"))
#         self.assertFalse(self.processor.can_process("doc"))
#         self.assertFalse(self.processor.can_process("pdf"))
    
#     def test_get_supported_formats(self):
#         """Test the supported_formats method."""
#         formats = self.processor.supported_formats
#         self.assertIn("xlsx", formats)
#         self.assertEqual(len(formats), 1)
    
#     def test_get_processor_info(self):
#         """Test the get_processor_info method."""
#         info = self.processor.get_processor_info()
#         self.assertEqual(info["name"], "XlsxProcessor")
#         self.assertTrue(info["available"])
#         self.assertIn("version", info)
    
#     def test_extract_text(self):
#         """Test the extract_text method."""
#         text = self.processor.extract_text(self.xlsx_bytes, self.test_options)
        
#         # Check that text contains sheet name
#         self.assertIn("Sheet: Test Sheet", text)
        
#         # Check that header is included
#         self.assertIn("ID", text)
#         self.assertIn("Name", text)
#         self.assertIn("Value", text)
        
#         # Check that data is included
#         self.assertIn("Item 1", text)
#         self.assertIn("100.5", text)
    
#     def test_extract_metadata(self):
#         """Test the extract_metadata method."""
#         metadata = self.processor.extract_metadata(self.xlsx_bytes, self.test_options)
        
#         # Check basic metadata
#         self.assertIn("file_size_bytes", metadata)
#         self.assertIn("sheet_count", metadata)
#         self.assertIn("sheets", metadata)
        
#         # Check sheet information
#         self.assertEqual(metadata["sheet_count"], 1)
#         self.assertIn("Test Sheet", metadata["sheets"])
        
#         # Check sheet statistics
#         self.assertIn("sheet_statistics", metadata)
#         self.assertEqual(len(metadata["sheet_statistics"]), 1)
#         self.assertEqual(metadata["sheet_statistics"][0]["name"], "Test Sheet")
    
#     def test_extract_structure(self):
#         """Test the extract_structure method."""
#         structure = self.processor.extract_structure(self.xlsx_bytes, self.test_options)
        
#         # Check workbook section
#         self.assertEqual(structure[0]["type"], "workbook")
        
#         # Check sheet section
#         sheet_section = next((s for s in structure if s["type"] == "sheet"), None)
#         self.assertIsNotNone(sheet_section)
#         self.assertEqual(sheet_section["name"], "Test Sheet")
        
#         # Check sample data
#         self.assertIn("sample_data", sheet_section["content"])
#         self.assertTrue(len(sheet_section["content"]["sample_data"]) > 0)
    
#     def test_process_document(self):
#         """Test the process_document method."""
#         text, metadata, sections = self.processor.process_document(self.xlsx_bytes, self.test_options)
        
#         # Check that text is not empty
#         self.assertTrue(len(text) > 0)
        
#         # Check that metadata includes sheet count
#         self.assertIn("sheet_count", metadata)
        
#         # Check that sections include structure
#         self.assertTrue(len(sections) > 0)
#         self.assertEqual(sections[0]["type"], "workbook")
    
#     def test_multi_sheet_document(self):
#         """Test processing a document with multiple sheets."""
#         text, metadata, sections = self.processor.process_document(self.xlsx_bytes_multi, self.test_options)
        
#         # Check sheet count
#         self.assertEqual(metadata["sheet_count"], 2)
        
#         # Check that both sheet names are in the sheets list
#         self.assertIn("Test Sheet", metadata["sheets"])
#         self.assertIn("Second Sheet", metadata["sheets"])
        
#         # Check that text contains both sheet names
#         self.assertIn("Sheet: Test Sheet", text)
#         self.assertIn("Sheet: Second Sheet", text)
        
#         # Check that structure contains both sheets
#         sheet_sections = [s for s in sections if s["type"] == "sheet"]
#         self.assertEqual(len(sheet_sections), 2)
#         sheet_names = [s["name"] for s in sheet_sections]
#         self.assertIn("Test Sheet", sheet_names)
#         self.assertIn("Second Sheet", sheet_names)
    
#     @patch('format_handlers.processors.xlsx_processor.OPENPYXL_AVAILABLE', False)
#     @patch('format_handlers.processors.xlsx_processor.XlsxProcessor.supported_formats')
#     def test_unavailable_processor(self, mock_get_supported_formats):
#         """Test behavior when openpyxl is not available."""
#         # Mock the supported_formats method to return an empty list
#         mock_get_supported_formats.return_value = []
        
#         # Create a new processor instance with the patched flag
#         processor = XlsxProcessor()
        
#         # Test that can_process returns False
#         self.assertFalse(processor.can_process("xlsx"))
        
#         # Test that extract_text raises ValueError
#         with self.assertRaises(ValueError):
#             processor.extract_text(self.xlsx_bytes, self.test_options)


# if __name__ == '__main__':
#     unittest.main()