# AI Agent Integration for GitHub PR Creation

This document describes how to use the software engineering tools with AI agents (GitHub Copilot, Claude Code, Gemini Code, etc.) to create pull requests programmatically when using this package as an MCP server.

## Overview

The `ai_agent_pr_creator` tool provides a high-level interface for AI coding assistants to:
- Create pull requests with proper attribution
- Update PRs based on feedback
- Analyze code changes before PR creation
- Integrate with existing development tools

## Available Tools

### 1. Code Analysis & Testing Tools (Already Exist)

These tools are already in the package and can be verified:

#### Development Tools (`ipfs_datasets_py/mcp_server/tools/development_tools/`)
- **`test_generator.py`** - Generate unit tests for code
- **`test_runner.py`** - Run tests and collect results
- **`codebase_search.py`** - Search codebase for patterns
- **`linting_tools.py`** - Lint Python code and fix issues
- **`documentation_generator.py`** - Generate documentation

#### GitHub Integration Tools
- **`github_cli_server_tools.py`** - GitHub CLI integration including:
  - `github_cli_status()` - Check GitHub CLI installation
  - `github_cli_install()` - Install GitHub CLI
  - `github_create_issue()` - Create GitHub issues
  - **`github_create_pull_request()` - Create pull requests (NEW)**
  - **`github_update_pull_request()` - Update existing PRs (NEW)**
  
#### Analysis Tools (`ipfs_datasets_py/mcp_server/tools/analysis_tools/`)
- **`analysis_tools.py`** - Code analysis utilities

### 2. AI Agent PR Tools (NEW)

#### `ai_agent_pr_creator.py`

**Functions:**

##### `create_ai_agent_pr()`
Create a GitHub pull request from an AI agent workflow with automatic attribution.

**Parameters:**
- `owner` (str): Repository owner
- `repo` (str): Repository name
- `branch_name` (str): Branch with changes
- `title` (str): PR title
- `description` (str): PR description
- `changes_summary` (List[Dict]): List of changes with file, action, description
- `agent_name` (str): AI agent name (e.g., "GitHub Copilot", "Claude Code")
- `base_branch` (str): Target branch (default: "main")
- `draft` (bool): Create as draft (default: False)
- `labels` (List[str]): Optional labels
- `auto_merge` (bool): Enable auto-merge (default: False)

**Returns:** Dictionary with PR URL, number, and creation status

**Example:**
```python
from ipfs_datasets_py.mcp_server.tools.software_engineering_tools.ai_agent_pr_creator import create_ai_agent_pr

result = create_ai_agent_pr(
    owner="myorg",
    repo="myrepo",
    branch_name="copilot/add-feature",
    title="Add new analysis feature",
    description="Implements XYZ analysis functionality",
    changes_summary=[
        {
            "file": "analyzer.py",
            "action": "modified",
            "description": "Added XYZ analysis method"
        },
        {
            "file": "test_analyzer.py",
            "action": "added",
            "description": "Added comprehensive tests for XYZ"
        }
    ],
    agent_name="GitHub Copilot",
    labels=["ai-generated", "enhancement"],
    draft=False
)

if result["success"]:
    print(f"PR created: {result['pr_url']}")
```

##### `update_ai_agent_pr()`
Update an existing AI agent pull request based on feedback.

**Parameters:**
- `owner` (str): Repository owner
- `repo` (str): Repository name
- `pr_number` (int): Pull request number
- `updates` (Dict): Updates to apply (title, description, add_changes, add_labels, remove_labels)
- `agent_name` (str): AI agent name

**Example:**
```python
result = update_ai_agent_pr(
    owner="myorg",
    repo="myrepo",
    pr_number=123,
    updates={
        "description": "Updated with additional improvements based on review",
        "add_changes": [
            {
                "file": "new_module.py",
                "action": "added",
                "description": "New module per review feedback"
            }
        ],
        "add_labels": ["ready-for-review"],
        "remove_labels": ["draft"]
    },
    agent_name="Claude Code"
)
```

##### `analyze_code_for_pr()`
Analyze code changes before creating a PR.

**Parameters:**
- `file_paths` (List[str]): Files to analyze
- `analysis_type` (str): "comprehensive", "quick", or "security"

**Returns:** Analysis results with issues, recommendations, and test coverage info

**Example:**
```python
result = analyze_code_for_pr(
    file_paths=["analyzer.py", "test_analyzer.py"],
    analysis_type="comprehensive"
)

# Check recommendations
for rec in result['pr_recommendations']:
    print(f"{rec['type']}: {rec['message']}")
```

## Using with AI Agents

### GitHub Copilot

When using GitHub Copilot with this package as an MCP server:

```python
# In your Copilot workspace
from ipfs_datasets_py.mcp_server.tools.software_engineering_tools.ai_agent_pr_creator import create_ai_agent_pr

# After making changes and committing to a branch
result = create_ai_agent_pr(
    owner="myorg",
    repo="myrepo",
    branch_name="copilot/feature-branch",
    title="Copilot: Add feature X",
    description="Implemented feature X with tests",
    changes_summary=changes,  # Your changes list
    agent_name="GitHub Copilot"
)
```

### Claude Code

```python
# In Claude Code/MCP session
import ipfs_datasets_py
from ipfs_datasets_py.mcp_server.tools.software_engineering_tools.ai_agent_pr_creator import create_ai_agent_pr

result = create_ai_agent_pr(
    owner="myorg",
    repo="myrepo",
    branch_name="claude/refactor-module",
    title="Claude Code: Refactor module for clarity",
    description="Refactored XYZ module to improve maintainability",
    changes_summary=[...],
    agent_name="Claude Code",
    draft=True  # Start as draft for human review
)
```

### Gemini Code

```python
# In Gemini Code workspace
from ipfs_datasets_py.mcp_server.tools.software_engineering_tools.ai_agent_pr_creator import create_ai_agent_pr

result = create_ai_agent_pr(
    owner="myorg",
    repo="myrepo",
    branch_name="gemini/optimize-performance",
    title="Gemini Code: Optimize performance",
    description="Applied performance optimizations",
    changes_summary=[...],
    agent_name="Gemini Code"
)
```

## MCP Server Integration

When this package is running as an MCP server, the tools are automatically exposed:

### Via MCP Tool Execution

```javascript
// JavaScript MCP SDK
const mcpClient = new MCPClient('/api/mcp');

const result = await mcpClient.executeTool(
    'software_engineering_tools',
    'create_ai_agent_pr',
    {
        owner: 'myorg',
        repo: 'myrepo',
        branch_name: 'feature/new-feature',
        title: 'Add new feature',
        description: 'Description here',
        changes_summary: [...],
        agent_name: 'My AI Agent'
    }
);
```

### Via Dashboard API

```bash
curl -X POST http://localhost:8899/api/mcp/tools/software_engineering_tools/create_ai_agent_pr/execute \
  -H "Content-Type: application/json" \
  -d '{
    "owner": "myorg",
    "repo": "myrepo",
    "branch_name": "feature/new-feature",
    "title": "Add new feature",
    "description": "Description here",
    "changes_summary": [...],
    "agent_name": "My AI Agent"
  }'
```

## Workflow Example

Complete workflow for AI agents:

```python
from ipfs_datasets_py.mcp_server.tools.software_engineering_tools.ai_agent_pr_creator import (
    analyze_code_for_pr,
    create_ai_agent_pr
)

# 1. Analyze code changes
analysis = analyze_code_for_pr(
    file_paths=["new_file.py", "modified_file.py"],
    analysis_type="comprehensive"
)

# 2. Check for issues
if analysis['issues']:
    print(f"Found {len(analysis['issues'])} issues to fix")
    # Fix issues...

# 3. Create PR with changes
changes_summary = [
    {"file": "new_file.py", "action": "added", "description": "New module"},
    {"file": "modified_file.py", "action": "modified", "description": "Updated logic"}
]

result = create_ai_agent_pr(
    owner="myorg",
    repo="myrepo",
    branch_name="agent/improvements",
    title="AI Agent: Code improvements",
    description="Automated code improvements based on analysis",
    changes_summary=changes_summary,
    agent_name="My AI Agent",
    labels=["ai-generated", "automated"]
)

if result['success']:
    print(f"✅ PR created: {result['pr_url']}")
    print(f"PR number: {result.get('pr_number')}")
```

## Tool Verification

To verify existing tools are working:

```python
# Check GitHub CLI
from ipfs_datasets_py.mcp_server.tools.development_tools.github_cli_server_tools import github_cli_status

status = github_cli_status()
print(f"GitHub CLI installed: {status['status']['installed']}")

# Check test generator
from ipfs_datasets_py.mcp_server.tools.development_tools.test_generator import test_generator

result = test_generator(
    file_path="my_module.py",
    test_framework="pytest"
)
print(f"Test generated: {result['success']}")

# Check linting tools
from ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools import lint_python_codebase

result = lint_python_codebase(path=".", files=["my_file.py"])
print(f"Linting completed: {result['success']}")
```

## Best Practices

1. **Always analyze before creating PR**: Use `analyze_code_for_pr()` to catch issues
2. **Use descriptive changes_summary**: Helps reviewers understand changes quickly
3. **Start with draft PRs**: Enable `draft=True` for complex changes
4. **Add appropriate labels**: Use "ai-generated" and descriptive labels
5. **Enable auto-merge cautiously**: Only for well-tested, low-risk changes
6. **Update PRs based on feedback**: Use `update_ai_agent_pr()` to address reviews

## Troubleshooting

### GitHub CLI not installed
```python
from ipfs_datasets_py.mcp_server.tools.development_tools.github_cli_server_tools import github_cli_install

result = github_cli_install(force=True)
if result['success']:
    print("GitHub CLI installed successfully")
```

### Authentication issues
```python
from ipfs_datasets_py.mcp_server.tools.development_tools.github_cli_server_tools import github_cli_auth_status

status = github_cli_auth_status()
if not status['status']['authenticated']:
    print("Please authenticate: gh auth login")
```

## Future Enhancements

- Automatic code review using AI
- Conflict resolution assistance
- PR template integration
- Automated testing before PR creation
- Integration with CI/CD status checks
