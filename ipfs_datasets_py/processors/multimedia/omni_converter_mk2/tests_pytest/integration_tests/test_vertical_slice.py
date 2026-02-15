"""
Pytest migration of test_vertical_slice.py

Integration test for a simple vertical slice: TXT file processing.
This test represents the DESIRED behavior, not current behavior.
Converted from unittest to pytest format while preserving all test logic.
"""
import tempfile
import os
import pytest
from pathlib import Path


@pytest.mark.integration
class TestVerticalSlice:
    
    def test_txt_file_processing_vertical_slice(self, tmp_path):
        """Test that a simple TXT file can be processed end-to-end."""
        # Arrange
        test_content = "Hello, this is a test file."
        
        # Use pytest's tmp_path fixture for better cleanup
        test_file = tmp_path / "test.txt"
        test_file.write_text(test_content)
        test_file_path = str(test_file)
        
        # Act - This is what SHOULD work
        from interfaces import make_cli
        cli = make_cli()
        
        # Simulate CLI processing a single file
        result: bool = cli.process_file(test_file_path)
        
        # Assert
        assert result is not None
        assert result is True

    def test_processing_pipeline_directly(self, tmp_path, capfd):
        """Test the core processing pipeline without CLI."""
        # Arrange
        test_content = "Direct pipeline test."
        
        # Use pytest's tmp_path fixture for better cleanup
        test_file = tmp_path / "test.txt"
        test_file.write_text(test_content)
        test_file_path = str(test_file)
        
        # Act
        from core import make_processing_pipeline
        from core._processing_result import ProcessingResult
        pipeline = make_processing_pipeline()
        
        result: ProcessingResult = pipeline.process_file(test_file_path)
        
        # Capture output for debugging (pytest provides capfd fixture)
        captured = capfd.readouterr()
        if captured.out:
            print(f"Captured stdout: {captured.out}")
        
        print(f"Processing result: {result}")
        
        # Assert
        assert result.success
        
        # Check if the output file was created
        output_file_path = result.output_path
        print(f"Output file path: {output_file_path}")
        assert Path(output_file_path).exists()

        # Check if the content matches
        with open(output_file_path, 'r') as output_file:
            output_content = output_file.read()
            print(f"Test Content: {test_content}\nOutput content: {output_content}")
            assert test_content in output_content