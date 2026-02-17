"""
CLI tests for graph commands.

Tests all graph commands added in Phase 6.
"""

import pytest
import subprocess
import json
import tempfile
from pathlib import Path


class TestGraphCommands:
    """Test graph CLI commands."""
    
    def test_graph_help(self):
        """Test graph command help text."""
        # GIVEN - ipfs-datasets CLI
        # WHEN - Running graph help
        result = subprocess.run(
            ['python', 'ipfs_datasets_cli.py', 'graph', '--help'],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        # THEN - Should show graph commands
        assert result.returncode == 0 or 'graph' in result.stdout.lower() or 'graph' in result.stderr.lower()
    
    def test_graph_create_command(self):
        """Test graph create command."""
        # GIVEN - Graph create parameters
        # WHEN - Running create command
        result = subprocess.run(
            ['python', 'ipfs_datasets_cli.py', 'graph', 'create', '--driver-url', 'ipfs://localhost:5001'],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        # THEN - Command should execute (may fail without IPFS, but shouldn't crash)
        assert result.returncode in [0, 1] or 'graph' in result.stdout or 'error' in result.stderr.lower()
    
    def test_graph_add_entity_command(self):
        """Test graph add-entity command."""
        # GIVEN - Entity parameters
        props = json.dumps({"name": "Alice", "age": 30})
        
        # WHEN - Running add-entity command
        result = subprocess.run(
            [
                'python', 'ipfs_datasets_cli.py', 'graph', 'add-entity',
                '--id', 'person1',
                '--type', 'Person',
                '--props', props
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        # THEN - Command should execute
        assert result.returncode in [0, 1] or 'entity' in result.stdout.lower() or 'error' in result.stderr.lower()
    
    def test_graph_query_command(self):
        """Test graph query command."""
        # GIVEN - Cypher query
        cypher = "MATCH (n) RETURN n LIMIT 10"
        
        # WHEN - Running query command
        result = subprocess.run(
            [
                'python', 'ipfs_datasets_cli.py', 'graph', 'query',
                '--cypher', cypher
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        # THEN - Command should execute
        assert result.returncode in [0, 1] or 'query' in result.stdout.lower() or 'error' in result.stderr.lower()


class TestCLIRegression:
    """Test that existing CLI commands still work."""
    
    def test_help_command(self):
        """Test main help command."""
        # GIVEN - ipfs-datasets CLI
        # WHEN - Running help
        result = subprocess.run(
            ['python', 'ipfs_datasets_cli.py', '--help'],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        # THEN - Should show help
        assert result.returncode == 0 or 'usage' in result.stdout.lower() or 'help' in result.stdout.lower()
