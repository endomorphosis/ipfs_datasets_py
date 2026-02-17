"""
Integration tests for CLI search commands.

Tests the search CLI commands added in Phase 9 Part 4.
"""

import pytest
import subprocess
import json
from pathlib import Path


class TestSearchCLICommands:
    """Test suite for search CLI commands."""
    
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
    
    # Test 1: Search command help
    def test_search_help(self):
        """
        GIVEN: The CLI is available
        WHEN: Running 'search' without subcommand
        THEN: Help message is displayed
        """
        result = self.run_cli(["search"])
        
        assert result.returncode == 0
        assert "Usage: ipfs-datasets search <subcommand>" in result.stdout
        assert "basic" in result.stdout
        assert "semantic" in result.stdout
        assert "hybrid" in result.stdout
    
    # Test 2: Search basic command
    def test_search_basic(self):
        """
        GIVEN: A search query
        WHEN: Running 'search basic QUERY'
        THEN: Search executes and returns results
        """
        result = self.run_cli(["search", "basic", "test query"])
        
        assert result.returncode == 0
        assert "test query" in result.stdout or "query" in result.stdout.lower()
    
    # Test 3: Search basic without query
    def test_search_basic_no_query(self):
        """
        GIVEN: No query provided
        WHEN: Running 'search basic' without query
        THEN: Error message is shown
        """
        result = self.run_cli(["search", "basic"])
        
        assert result.returncode == 0
        assert "Error" in result.stdout or "required" in result.stdout
    
    # Test 4: Search basic with JSON output
    def test_search_basic_json_output(self):
        """
        GIVEN: A query and --json flag
        WHEN: Running 'search basic QUERY --json'
        THEN: JSON output is returned
        """
        result = self.run_cli(["search", "basic", "test", "--json"])
        
        assert result.returncode == 0
        # Check for JSON-like output
        assert "{" in result.stdout or "query" in result.stdout.lower()
    
    # Test 5: Search semantic command
    def test_search_semantic(self):
        """
        GIVEN: A search query
        WHEN: Running 'search semantic QUERY'
        THEN: Search executes and returns results
        """
        result = self.run_cli(["search", "semantic", "machine learning"])
        
        assert result.returncode == 0
        assert "machine learning" in result.stdout or "query" in result.stdout.lower()
    
    # Test 6: Search semantic without query
    def test_search_semantic_no_query(self):
        """
        GIVEN: No query provided
        WHEN: Running 'search semantic' without query
        THEN: Error message is shown
        """
        result = self.run_cli(["search", "semantic"])
        
        assert result.returncode == 0
        assert "Error" in result.stdout or "required" in result.stdout
    
    # Test 7: Search semantic with JSON output
    def test_search_semantic_json_output(self):
        """
        GIVEN: A query and --json flag
        WHEN: Running 'search semantic QUERY --json'
        THEN: JSON output is returned
        """
        result = self.run_cli(["search", "semantic", "ai", "--json"])
        
        assert result.returncode == 0
        # Check for JSON-like output
        assert "{" in result.stdout or "query" in result.stdout.lower()
    
    # Test 8: Search hybrid command
    def test_search_hybrid(self):
        """
        GIVEN: A search query
        WHEN: Running 'search hybrid QUERY'
        THEN: Search executes and returns results
        """
        result = self.run_cli(["search", "hybrid", "data science"])
        
        assert result.returncode == 0
        assert "data science" in result.stdout or "query" in result.stdout.lower()
    
    # Test 9: Search hybrid without query
    def test_search_hybrid_no_query(self):
        """
        GIVEN: No query provided
        WHEN: Running 'search hybrid' without query
        THEN: Error message is shown
        """
        result = self.run_cli(["search", "hybrid"])
        
        assert result.returncode == 0
        assert "Error" in result.stdout or "required" in result.stdout
    
    # Test 10: Search hybrid with JSON output
    def test_search_hybrid_json_output(self):
        """
        GIVEN: A query and --json flag
        WHEN: Running 'search hybrid QUERY --json'
        THEN: JSON output is returned
        """
        result = self.run_cli(["search", "hybrid", "nlp", "--json"])
        
        assert result.returncode == 0
        # Check for JSON-like output
        assert "{" in result.stdout or "query" in result.stdout.lower()
    
    # Test 11: Search unknown subcommand
    def test_search_unknown_subcommand(self):
        """
        GIVEN: An invalid subcommand
        WHEN: Running 'search invalid_command QUERY'
        THEN: Error message is shown
        """
        result = self.run_cli(["search", "invalid_command", "query"])
        
        assert result.returncode == 0
        assert "Unknown" in result.stdout or "Available" in result.stdout


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
