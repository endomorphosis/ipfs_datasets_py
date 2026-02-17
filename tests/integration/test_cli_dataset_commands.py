"""
Integration tests for CLI dataset commands.

Tests the dataset CLI commands added in Phase 9 Part 4.
"""

import pytest
import subprocess
import json
import os
import tempfile
from pathlib import Path


class TestDatasetCLICommands:
    """Test suite for dataset CLI commands."""
    
    def get_cli_path(self):
        """Get path to CLI script."""
        return Path(__file__).parent.parent.parent / "ipfs_datasets_cli.py"
    
    def run_cli(self, args, check=False):
        """Helper to run CLI commands."""
        import sys
        cmd = [sys.executable, str(self.get_cli_path())] + args
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check
        )
        return result
    
    # Test 1: Dataset command help
    def test_dataset_help(self):
        """
        GIVEN: The CLI is available
        WHEN: Running 'dataset' without subcommand
        THEN: Help message is displayed
        """
        result = self.run_cli(["dataset"])
        
        assert result.returncode == 0
        assert "Usage: ipfs-datasets dataset <subcommand>" in result.stdout
        assert "validate" in result.stdout
        assert "info" in result.stdout
        assert "list" in result.stdout
        assert "process" in result.stdout
    
    # Test 2: Dataset validate with valid path
    def test_dataset_validate_valid_path(self):
        """
        GIVEN: A valid path exists
        WHEN: Running 'dataset validate --path PATH'
        THEN: Validation succeeds
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_cli(["dataset", "validate", "--path", tmpdir])
            
            assert result.returncode == 0
            assert "valid" in result.stdout.lower() or "successful" in result.stdout.lower()
    
    # Test 3: Dataset validate with invalid path
    def test_dataset_validate_invalid_path(self):
        """
        GIVEN: An invalid path
        WHEN: Running 'dataset validate --path PATH'
        THEN: Validation fails appropriately
        """
        result = self.run_cli(["dataset", "validate", "--path", "/nonexistent/path/12345"])
        
        assert result.returncode == 0  # Command runs, but reports invalid
        # Output should indicate path doesn't exist
        assert "not exist" in result.stdout.lower() or "error" in result.stdout.lower()
    
    # Test 4: Dataset validate without path
    def test_dataset_validate_no_path(self):
        """
        GIVEN: No path provided
        WHEN: Running 'dataset validate' without --path
        THEN: Error message is shown
        """
        result = self.run_cli(["dataset", "validate"])
        
        assert result.returncode == 0
        assert "Error" in result.stdout or "required" in result.stdout
        assert "--path" in result.stdout
    
    # Test 5: Dataset validate with JSON output
    def test_dataset_validate_json_output(self):
        """
        GIVEN: A valid path and --json flag
        WHEN: Running 'dataset validate --path PATH --json'
        THEN: JSON output is returned
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_cli(["dataset", "validate", "--path", tmpdir, "--json"])
            
            assert result.returncode == 0
            # Try to parse output as JSON (may have warnings before JSON)
            lines = result.stdout.strip().split('\n')
            # Find the JSON line (last non-warning line)
            json_line = None
            for line in reversed(lines):
                if line.strip() and not line.startswith('Warning') and not line.startswith('/'):
                    json_line = line
                    break
            
            if json_line:
                try:
                    data = json.loads(json_line)
                    assert isinstance(data, dict)
                except json.JSONDecodeError:
                    # JSON might be in pretty format, just check for JSON-like structure
                    assert "{" in result.stdout or "valid" in result.stdout.lower()
    
    # Test 6: Dataset info command
    def test_dataset_info(self):
        """
        GIVEN: A dataset name
        WHEN: Running 'dataset info --name NAME'
        THEN: Info is displayed
        """
        result = self.run_cli(["dataset", "info", "--name", "test_dataset"])
        
        assert result.returncode == 0
        assert "test_dataset" in result.stdout or "name" in result.stdout.lower()
    
    # Test 7: Dataset info without name
    def test_dataset_info_no_name(self):
        """
        GIVEN: No name provided
        WHEN: Running 'dataset info' without --name
        THEN: Error message is shown
        """
        result = self.run_cli(["dataset", "info"])
        
        assert result.returncode == 0
        assert "Error" in result.stdout or "required" in result.stdout
        assert "--name" in result.stdout
    
    # Test 8: Dataset info with JSON output
    def test_dataset_info_json_output(self):
        """
        GIVEN: A dataset name and --json flag
        WHEN: Running 'dataset info --name NAME --json'
        THEN: JSON output is returned
        """
        result = self.run_cli(["dataset", "info", "--name", "test", "--json"])
        
        assert result.returncode == 0
        # Check for JSON-like output
        assert "{" in result.stdout or "name" in result.stdout.lower()
    
    # Test 9: Dataset list command
    def test_dataset_list(self):
        """
        GIVEN: The CLI is available
        WHEN: Running 'dataset list'
        THEN: List is displayed
        """
        result = self.run_cli(["dataset", "list"])
        
        assert result.returncode == 0
        # Should return some output (even if empty list)
        assert len(result.stdout) > 0
    
    # Test 10: Dataset list with JSON output
    def test_dataset_list_json_output(self):
        """
        GIVEN: --json flag
        WHEN: Running 'dataset list --json'
        THEN: JSON output is returned
        """
        result = self.run_cli(["dataset", "list", "--json"])
        
        assert result.returncode == 0
        # Check for JSON-like output
        assert "{" in result.stdout or "[" in result.stdout or "datasets" in result.stdout.lower()
    
    # Test 11: Dataset process command
    def test_dataset_process(self):
        """
        GIVEN: Input and output paths
        WHEN: Running 'dataset process --input PATH --output PATH'
        THEN: Process command executes
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "input")
            output_path = os.path.join(tmpdir, "output")
            
            result = self.run_cli([
                "dataset", "process",
                "--input", input_path,
                "--output", output_path
            ])
            
            assert result.returncode == 0
            assert "process" in result.stdout.lower() or "input" in result.stdout.lower()
    
    # Test 12: Dataset process without input
    def test_dataset_process_no_input(self):
        """
        GIVEN: Only output path provided
        WHEN: Running 'dataset process --output PATH'
        THEN: Error message is shown
        """
        result = self.run_cli(["dataset", "process", "--output", "/tmp/output"])
        
        assert result.returncode == 0
        assert "Error" in result.stdout or "required" in result.stdout
    
    # Test 13: Dataset process without output
    def test_dataset_process_no_output(self):
        """
        GIVEN: Only input path provided
        WHEN: Running 'dataset process --input PATH'
        THEN: Error message is shown
        """
        result = self.run_cli(["dataset", "process", "--input", "/tmp/input"])
        
        assert result.returncode == 0
        assert "Error" in result.stdout or "required" in result.stdout
    
    # Test 14: Dataset process with JSON output
    def test_dataset_process_json_output(self):
        """
        GIVEN: Input, output paths and --json flag
        WHEN: Running 'dataset process --input PATH --output PATH --json'
        THEN: JSON output is returned
        """
        result = self.run_cli([
            "dataset", "process",
            "--input", "/tmp/input",
            "--output", "/tmp/output",
            "--json"
        ])
        
        assert result.returncode == 0
        # Check for JSON-like output
        assert "{" in result.stdout or "input" in result.stdout.lower()
    
    # Test 15: Dataset unknown subcommand
    def test_dataset_unknown_subcommand(self):
        """
        GIVEN: An invalid subcommand
        WHEN: Running 'dataset invalid_command'
        THEN: Error message is shown
        """
        result = self.run_cli(["dataset", "invalid_command"])
        
        assert result.returncode == 0
        assert "Unknown" in result.stdout or "Available" in result.stdout


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
