"""Dependency Chain Analyzer — thin MCP shim. Business logic in processors.development.dependency_analysis_engine."""
from ipfs_datasets_py.processors.development.dependency_analysis_engine import (  # noqa: F401
    analyze_dependency_chain,
    parse_package_json_dependencies,
    parse_requirements_txt,
    suggest_dependency_improvements,
)
