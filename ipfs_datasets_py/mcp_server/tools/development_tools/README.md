# Development Tools

MCP tools for software development workflows: GitHub/GitLab operations, AI assistant CLI
integrations (Claude, Gemini, Copilot, VS Code), codebase search, documentation generation,
test generation, linting, and automated PR review.

## Tools

### GitHub & Version Control

| File | Function(s) | Description |
|------|-------------|-------------|
| `github_cli_server_tools.py` | `github_create_pr()`, `github_list_issues()`, `github_search_repos()`, … | GitHub CLI integration (create PRs, manage issues, search repos) |
| `github_cli_tools.py` | `github_*()` | Compatibility shim — delegates to `github_cli_server_tools` |
| `automated_pr_review_tools.py` | `review_pr()`, `analyze_pr_diff()` | AI-powered automated pull request review |

### AI Assistant CLI Integrations

| File | Function(s) | Description |
|------|-------------|-------------|
| `claude_cli_server_tools.py` | `claude_complete()`, `claude_chat()`, `claude_analyze_code()`, … | Anthropic Claude CLI integration |
| `claude_cli_tools.py` | — | Compatibility shim for `claude_cli_server_tools` |
| `gemini_cli_server_tools.py` | `gemini_complete()`, `gemini_chat()`, `gemini_analyze_file()`, … | Google Gemini CLI integration |
| `gemini_cli_tools.py` | — | Compatibility shim for `gemini_cli_server_tools` |
| `copilot_cli_tools.py` | `copilot_suggest()`, `copilot_explain()` | GitHub Copilot CLI integration |
| `vscode_cli_tools.py` | `vscode_open()`, `vscode_run_task()` | VS Code CLI integration |

### Code Intelligence

| File | Function(s) | Description |
|------|-------------|-------------|
| `codebase_search_engine.py` | `CodebaseSearchEngine` class | Reusable engine for file/symbol/pattern search in a codebase |
| `codebase_search.py` | `search_codebase()`, `find_symbol()`, `grep_codebase()` | MCP thin wrapper around `CodebaseSearchEngine` |

### Documentation & Testing

| File | Function(s) | Description |
|------|-------------|-------------|
| `documentation_generator.py` | `generate_docs()`, `generate_module_docs()` | Auto-generate markdown documentation from docstrings |
| `documentation_generator_simple.py` | `generate_simple_docs()` | Simplified documentation generator |
| `test_generator.py` | `generate_tests()`, `generate_unit_test()` | AI-assisted test generation |
| `test_runner.py` | `run_tests()`, `run_test_suite()` | Execute tests and return structured results |

### Code Quality

| File | Function(s) | Description |
|------|-------------|-------------|
| `linting_engine.py` | `LintingEngine` class | Reusable linting engine for multiple languages |
| `linting_tools.py` | `lint_file()`, `lint_directory()`, `fix_lint_issues()` | MCP thin wrapper around `LintingEngine` |

### Utilities

| File | Function(s) | Description |
|------|-------------|-------------|
| `base_tool.py` | `BaseTool` class | Abstract base for development tools |
| `config.py` | `DevToolsConfig` | Configuration dataclass for development tools |
| `templates/` | — | Code templates for test generation and documentation |

## Usage

### GitHub operations

```python
from ipfs_datasets_py.mcp_server.tools.development_tools import (
    github_create_pr, github_list_issues
)

# Create a pull request
pr = await github_create_pr(
    owner="my-org",
    repo="my-repo",
    title="Fix: resolve dataset loading issue",
    body="## Summary\nThis PR fixes...",
    head="feature/fix-loading",
    base="main",
    draft=False
)

# List issues
issues = await github_list_issues(
    owner="my-org",
    repo="my-repo",
    state="open",
    labels=["bug"],
    max_results=20
)
```

### Codebase search

```python
from ipfs_datasets_py.mcp_server.tools.development_tools import search_codebase

result = await search_codebase(
    root_path="/home/user/project",
    query="class DatasetLoader",
    search_type="symbol",      # "symbol" | "text" | "regex" | "file"
    file_extensions=[".py"],
    max_results=20
)
```

### Generate documentation

```python
from ipfs_datasets_py.mcp_server.tools.development_tools import generate_docs

result = await generate_docs(
    source_path="/home/user/project/src",
    output_path="/home/user/project/docs",
    format="markdown",         # "markdown" | "rst" | "html"
    include_private=False
)
```

### Generate tests

```python
from ipfs_datasets_py.mcp_server.tools.development_tools import generate_tests

result = await generate_tests(
    source_file="/home/user/project/src/loader.py",
    output_file="/home/user/project/tests/test_loader.py",
    test_framework="pytest",
    coverage_target=80
)
```

### Lint a file

```python
from ipfs_datasets_py.mcp_server.tools.development_tools import lint_file

result = await lint_file(
    file_path="/home/user/project/src/loader.py",
    linters=["flake8", "mypy"],
    fix=True                   # Auto-fix fixable issues
)
```

### Claude AI code analysis

```python
from ipfs_datasets_py.mcp_server.tools.development_tools import claude_analyze_code

result = await claude_analyze_code(
    code=open("/home/user/project/src/loader.py").read(),
    task="review",             # "review" | "explain" | "refactor" | "test"
    focus=["security", "performance"]
)
```

## Core Module

All business logic delegates to:
- `ipfs_datasets_py.utils.github_cli.GitHubCLI`
- `ipfs_datasets_py.utils.claude_cli.ClaudeCLI`
- `ipfs_datasets_py.utils.gemini_cli.GeminiCLI`

## Dependencies

**Required:**
- Standard library: `subprocess`, `os`, `pathlib`, `re`

**Optional (tools degrade gracefully):**
- `gh` CLI binary — for GitHub operations
- `claude` CLI binary — for Claude CLI tools
- `gemini` CLI binary — for Gemini CLI tools
- `flake8`, `mypy`, `black` — for linting tools
- `pytest` — for test runner

## Status

| Tool Group | Status |
|------------|--------|
| GitHub CLI tools | ✅ Production ready |
| Claude CLI tools | ✅ Production ready |
| Gemini CLI tools | ✅ Production ready |
| Codebase search | ✅ Production ready |
| Documentation generator | ✅ Production ready |
| Test generator | ✅ Production ready |
| Linting tools | ✅ Production ready |
| Automated PR review | ✅ Production ready |
