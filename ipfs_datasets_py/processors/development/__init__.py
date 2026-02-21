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

from .ai_agent_pr_engine import (
    create_ai_agent_pr,
    update_ai_agent_pr,
    analyze_code_for_pr,
)
from .dag_workflow_engine import (
    create_workflow_dag,
    plan_speculative_execution,
)
from .dependency_analysis_engine import (
    analyze_dependency_chain,
    parse_package_json_dependencies,
    parse_requirements_txt,
    suggest_dependency_improvements,
)
from .kubernetes_log_engine import (
    parse_kubernetes_logs,
    analyze_pod_health,
)
from .github_actions_engine import (
    analyze_github_actions,
    parse_workflow_logs,
)
from .error_pattern_engine import (
    detect_error_patterns,
    suggest_fixes,
)
from .auto_healing_engine import (
    coordinate_auto_healing,
    monitor_healing_effectiveness,
)
from .systemd_log_engine import (
    parse_systemd_logs,
    analyze_service_health,
)
from .gpu_provisioning_engine import (
    predict_gpu_needs,
    analyze_resource_utilization,
)
