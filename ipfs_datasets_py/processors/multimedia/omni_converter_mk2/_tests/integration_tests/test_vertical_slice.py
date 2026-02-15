"""
Integration test for a simple vertical slice: TXT file processing.
This test represents the DESIRED behavior, not current behavior.
"""
import tempfile
import os
import unittest
from pathlib import Path


class TestVerticalSlice(unittest.TestCase):
    
    def test_txt_file_processing_vertical_slice(self):
        """Test that a simple TXT file can be processed end-to-end."""
        # Arrange
        test_content = "Hello, this is a test file."
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as tf:
            tf.write(test_content)
            test_file_path = tf.name
        
        try:
            # Act - This is what SHOULD work
            from interfaces import make_cli
            cli = make_cli()
            
            # Simulate CLI processing a single file
            result: bool = cli.process_file(test_file_path)
            
            # Assert
            self.assertIsNotNone(result)
            self.assertTrue(result)

        finally:
            # Cleanup
            os.unlink(test_file_path)

    def test_processing_pipeline_directly(self):
        """Test the core processing pipeline without CLI."""
        # Arrange
        test_content = "Direct pipeline test."
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as tf:
            tf.write(test_content)
            test_file_path = tf.name
        
        try:
            # Act
            from core import make_processing_pipeline
            from core._processing_result import ProcessingResult
            pipeline = make_processing_pipeline()
            
            result: ProcessingResult = pipeline.process_file(test_file_path)
            print(f"Processing result: {result}")
            
            # Assert
            self.assertTrue(result.success)
            print(f"Processing result: {result}")

            # Check if the output file was created
            output_file_path = result.output_path
            print(f"Output file path: {output_file_path}")
            self.assertTrue(Path(output_file_path).exists())

            # Check if the content matches
            with open(output_file_path, 'r') as output_file:
                output_content = output_file.read()
                print(f"Test Content: {test_content}\nOutput content: {output_content}")
                self.assertIn(test_content, output_content)

        finally:
            os.unlink(test_file_path)
            #os.unlink(output_file_path)


if __name__ == "__main__":
    unittest.main()
