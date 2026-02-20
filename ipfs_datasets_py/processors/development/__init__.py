"""
Development tooling package for ipfs_datasets_py.

Provides codebase search, linting, and software engineering theorems
for temporal deontic logic reasoning.

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
]
