"""
Development Tools Module for IPFS Datasets MCP Server.

This module contains tools migrated from claudes_toolbox for development
and code analysis, enhanced with dataset-aware capabilities and IPFS integration.

Available Tools:
- test_generator: Generate comprehensive test files for Python code
- documentation_generator: Generate documentation from Python code
- linting_tools: Python code linting and formatting tools
- test_runner: Run comprehensive test suites with reporting
- codebase_search: Advanced pattern matching and code search
"""

from .test_generator import test_generator
from .documentation_generator import documentation_generator
from .linting_tools import lint_python_codebase
from .test_runner import run_comprehensive_tests
from .codebase_search import codebase_search

__all__ = [
    'test_generator',
    'documentation_generator',
    'lint_python_codebase',
    'run_comprehensive_tests',
    'codebase_search',
]

# Tool metadata for MCP server registration
DEVELOPMENT_TOOLS = {
    'test_generator': {
        'name': 'test_generator',
        'description': 'Generate comprehensive test files for Python code with pytest framework',
        'function': test_generator,
        'category': 'testing'
    },
    'documentation_generator': {
        'name': 'documentation_generator',
        'description': 'Generate documentation from Python code using AST analysis and templates',
        'function': documentation_generator,
        'category': 'documentation'
    },
    'lint_python_codebase': {
        'name': 'lint_python_codebase',
        'description': 'Lint and format Python codebase with dataset-specific rules',
        'function': lint_python_codebase,
        'category': 'code_quality'
    },
    'run_comprehensive_tests': {
        'name': 'run_comprehensive_tests',
        'description': 'Run comprehensive test suites including pytest, mypy, and flake8',
        'function': run_comprehensive_tests,
        'category': 'testing'
    },
    'codebase_search': {
        'name': 'codebase_search',
        'description': 'Advanced pattern matching and code search with regex support',
        'function': codebase_search,
        'category': 'search'
    },
}
