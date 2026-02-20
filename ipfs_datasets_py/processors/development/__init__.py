"""
Development tooling package for ipfs_datasets_py.

Provides codebase search, linting, software engineering theorems, and JSON-to-Python
AST conversion for temporal deontic logic reasoning.

Reusable by:
- MCP server tools (mcp_server/tools/development_tools/, mcp_server/tools/software_engineering_tools/)
- CLI commands
- Direct Python imports
"""
from .codebase_search_engine import (
    SearchMatch,
    FileSearchResult,
    SearchSummary,
    CodebaseSearchResult,
    CodebaseSearchEngine,
)
from .linting_engine import (
    LintIssue,
    LintResult,
    PythonLinter,
    DatasetLinter,
)
from .software_theorems_engine import (
    SOFTWARE_THEOREMS,
    list_software_theorems,
    validate_against_theorem,
    apply_theorem_actions,
)
from .json_to_python_engine import (
    json_to_python_file,
    _JsonToAst,
    _UnKnownNodeException,
)
from .test_generator_engine import (
    TestGeneratorCore,
    TestGeneratorConfig,
    TestGeneratorError,
    TestGeneratorValidationError,
    TestGeneratorExecutionError,
    generate_test_file,
    UNITTEST_TEMPLATE,
    PYTEST_TEMPLATE,
)

__all__ = [
    "SearchMatch",
    "FileSearchResult",
    "SearchSummary",
    "CodebaseSearchResult",
    "CodebaseSearchEngine",
    "LintIssue",
    "LintResult",
    "PythonLinter",
    "DatasetLinter",
    "SOFTWARE_THEOREMS",
    "list_software_theorems",
    "validate_against_theorem",
    "apply_theorem_actions",
    "json_to_python_file",
    "_JsonToAst",
    "_UnKnownNodeException",
    "TestGeneratorCore",
    "TestGeneratorConfig",
    "TestGeneratorError",
    "TestGeneratorValidationError",
    "TestGeneratorExecutionError",
    "generate_test_file",
    "UNITTEST_TEMPLATE",
    "PYTEST_TEMPLATE",
]
