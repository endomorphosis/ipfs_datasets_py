"""Tests for the MCP server."""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    import pytest
except ImportError:
    # pytest not available, tests will use unittest instead
    pytest = None
