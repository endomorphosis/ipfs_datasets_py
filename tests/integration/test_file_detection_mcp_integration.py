"""
Integration tests for File Detection MCP Tools.

Tests the MCP tools for file type detection.
"""

import os
import tempfile
import json
import pytest
from pathlib import Path

from ipfs_datasets_py.mcp_server.tools.file_detection_tools.detect_file_type import detect_file_type
from ipfs_datasets_py.mcp_server.tools.file_detection_tools.batch_detect_file_types import batch_detect_file_types
from ipfs_datasets_py.mcp_server.tools.file_detection_tools.analyze_detection_accuracy import analyze_detection_accuracy


class TestFileDetectionMCPIntegration:
    """Integration tests for file detection MCP tools"""
    
    @pytest.fixture
    def temp_test_dir(self):
        """Create temporary directory with test files"""
        temp_dir = tempfile.mkdtemp()
        
        # Create various test files
        files = {
            'document.pdf': b'%PDF-1.4\n%EOF\n',
            'text.txt': b'This is a text file.',
            'data.json': b'{"key": "value"}',
            'script.py': b'#!/usr/bin/env python\nprint("hello")',
            'readme.md': b'# Readme\nThis is markdown.',
        }
        
        for filename, content in files.items():
            file_path = Path(temp_dir) / filename
            file_path.write_bytes(content)
        
        yield temp_dir
        
        # Cleanup
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    def test_detect_file_type_tool(self, temp_test_dir):
        """
        GIVEN: A PDF file
        WHEN: Using detect_file_type tool
        THEN: Should return detection results
        """
        pdf_path = Path(temp_test_dir) / 'document.pdf'
        result = detect_file_type(str(pdf_path))
        
        assert result is not None
        assert 'mime_type' in result
        assert 'confidence' in result
        assert 'method' in result
        
        # Should detect as PDF
        if result.get('mime_type'):
            assert 'pdf' in result['mime_type'].lower() or 'application' in result['mime_type']
    
    def test_detect_file_type_with_methods(self, temp_test_dir):
        """
        GIVEN: A text file and specific methods
        WHEN: Using detect_file_type tool with methods parameter
        THEN: Should use specified methods
        """
        text_path = Path(temp_test_dir) / 'text.txt'
        result = detect_file_type(str(text_path), methods=['extension'])
        
        assert result is not None
        assert result['method'] == 'extension'
        assert 'text' in result.get('mime_type', '').lower()
    
    def test_detect_file_type_with_strategy(self, temp_test_dir):
        """
        GIVEN: A file and a detection strategy
        WHEN: Using detect_file_type tool with strategy parameter
        THEN: Should apply the strategy
        """
        json_path = Path(temp_test_dir) / 'data.json'
        result = detect_file_type(str(json_path), strategy='fast')
        
        assert result is not None
        assert 'mime_type' in result
        assert 'all_results' in result
    
    def test_batch_detect_file_types_with_directory(self, temp_test_dir):
        """
        GIVEN: A directory with multiple files
        WHEN: Using batch_detect_file_types tool
        THEN: Should detect types for all files
        """
        result = batch_detect_file_types(directory=temp_test_dir)
        
        assert result is not None
        assert 'results' in result
        assert 'total_files' in result
        assert 'successful' in result
        assert 'failed' in result
        
        # Should process all 5 files
        assert result['total_files'] == 5
        assert len(result['results']) == 5
        
        # Check that results contain expected files
        result_keys = set(result['results'].keys())
        assert any('document.pdf' in k for k in result_keys)
        assert any('text.txt' in k for k in result_keys)
    
    def test_batch_detect_with_pattern(self, temp_test_dir):
        """
        GIVEN: A directory and a file pattern
        WHEN: Using batch_detect_file_types with pattern
        THEN: Should only process matching files
        """
        result = batch_detect_file_types(
            directory=temp_test_dir,
            pattern='*.txt'
        )
        
        assert result is not None
        assert 'results' in result
        
        # Should only find .txt files
        assert result['total_files'] >= 1
        for file_path in result['results'].keys():
            assert file_path.endswith('.txt')
    
    def test_batch_detect_with_export(self, temp_test_dir):
        """
        GIVEN: Multiple files and an export path
        WHEN: Using batch_detect_file_types with export_path
        THEN: Should export results to JSON file
        """
        export_path = Path(temp_test_dir) / 'results.json'
        
        result = batch_detect_file_types(
            directory=temp_test_dir,
            export_path=str(export_path)
        )
        
        assert result is not None
        assert 'export_path' in result
        assert result['export_path'] == str(export_path)
        
        # Verify exported file exists and is valid JSON
        assert export_path.exists()
        with open(export_path) as f:
            exported_data = json.load(f)
        
        assert isinstance(exported_data, dict)
        assert len(exported_data) == result['total_files']
    
    def test_batch_detect_with_file_list(self, temp_test_dir):
        """
        GIVEN: A list of specific file paths
        WHEN: Using batch_detect_file_types with file_paths
        THEN: Should process only specified files
        """
        file_paths = [
            str(Path(temp_test_dir) / 'text.txt'),
            str(Path(temp_test_dir) / 'data.json')
        ]
        
        result = batch_detect_file_types(file_paths=file_paths)
        
        assert result is not None
        assert result['total_files'] == 2
        assert len(result['results']) == 2
    
    def test_analyze_detection_accuracy(self, temp_test_dir):
        """
        GIVEN: A directory with multiple files
        WHEN: Using analyze_detection_accuracy tool
        THEN: Should return accuracy analysis
        """
        result = analyze_detection_accuracy(directory=temp_test_dir)
        
        assert result is not None
        assert 'total_files' in result
        assert 'method_availability' in result
        assert 'method_success_rates' in result
        assert 'agreement_rate' in result
        assert 'avg_confidence_by_method' in result
        
        # Should analyze all files
        assert result['total_files'] == 5
        
        # Should have at least extension method available
        assert 'extension' in result['method_availability']
        
        # Success rates should be between 0 and 1
        for rate in result['method_success_rates'].values():
            assert 0.0 <= rate <= 1.0
        
        # Agreement rate should be between 0 and 1
        assert 0.0 <= result['agreement_rate'] <= 1.0
    
    def test_analyze_accuracy_with_pattern(self, temp_test_dir):
        """
        GIVEN: A directory and file pattern
        WHEN: Using analyze_detection_accuracy with pattern
        THEN: Should analyze only matching files
        """
        result = analyze_detection_accuracy(
            directory=temp_test_dir,
            pattern='*.py'
        )
        
        assert result is not None
        assert 'total_files' in result
        
        # Should find the Python file
        assert result['total_files'] >= 1
    
    def test_detect_nonexistent_file(self):
        """
        GIVEN: A path to nonexistent file
        WHEN: Using detect_file_type tool
        THEN: Should return error result
        """
        result = detect_file_type('/nonexistent/file.pdf')
        
        assert result is not None
        assert result.get('mime_type') is None
        assert 'error' in result or result.get('confidence') == 0.0
    
    def test_batch_detect_empty_directory(self):
        """
        GIVEN: An empty directory
        WHEN: Using batch_detect_file_types
        THEN: Should return empty results
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            result = batch_detect_file_types(directory=temp_dir)
            
            assert result is not None
            assert result['total_files'] == 0
            assert len(result['results']) == 0
    
    def test_analyze_accuracy_empty_directory(self):
        """
        GIVEN: An empty directory
        WHEN: Using analyze_detection_accuracy
        THEN: Should return appropriate error
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            result = analyze_detection_accuracy(directory=temp_dir)
            
            assert result is not None
            assert result['total_files'] == 0 or 'error' in result
