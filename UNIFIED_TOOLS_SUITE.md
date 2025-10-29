# Unified Software Engineering Tools Suite

## Overview

The Software Engineering Dashboard now integrates **all development tools** from the ipfs_datasets_py package into one coherent, unified interface accessible at `/mcp/software`.

## Complete Tools Suite (15 Categories)

### 1. **Repository Analysis**
- GitHub repository scraping
- Repository health scoring
- Pull request analysis
- Issue tracking

### 2. **CI/CD Integration**
- GitHub Actions analysis
- Workflow performance metrics
- Failure pattern detection
- Cost estimation

### 3. **Log Analysis**
- Systemd log parsing
- Kubernetes log analysis
- Pod/container health monitoring
- Error pattern detection

### 4. **Dependency Management**
- Circular dependency detection
- Dependency depth analysis
- Coupling analysis
- Improvement recommendations

### 5. **Workflow Orchestration**
- DAG creation and validation
- dagseq2dagseq speculative execution
- Critical path analysis
- Parallel execution groups

### 6. **Resource Prediction**
- GPU provisioning forecasting
- Call stack-based predictions
- Resource utilization tracking
- Timeline generation

### 7. **Auto-Healing**
- Error pattern detection (10+ patterns)
- Automated fix suggestions
- Healing effectiveness tracking
- Dry-run mode support

### 8. **Software Theorems**
- 10 temporal deontic logic rules
- Theorem validation engine
- Action recommendations
- Multi-domain support (DevOps, security, quality, operations, MLOps)

### 9. **Testing Tools** (NEW)
- **Test Generator**: Generate unit tests for Python code
  - Supports pytest and unittest frameworks
  - Automatic fixture generation
  - Parametrized test support
- **Test Runner**: Run tests with comprehensive reporting
  - Coverage analysis
  - Performance metrics
  - Detailed failure reporting

### 10. **Code Linting** (NEW)
- **Python Linting**: Code quality analysis
  - Auto-fix support
  - Multiple linter integration (pylint, flake8, black)
  - Selective file linting
  - Issue categorization

### 11. **Documentation Generation** (NEW)
- **Auto-Documentation**: Generate docs from code
  - Multiple formats: Markdown, RST, HTML
  - API documentation extraction
  - Docstring parsing
  - Cross-reference generation

### 12. **Codebase Search** (NEW)
- **Pattern Search**: Find code patterns
  - Regular expression support
  - Case-sensitive search
  - Multi-file search
  - Symbol and function lookup

### 13. **AI Agent PR Creation** (NEW)
- **GitHub PR Creation**: Create PRs from AI agents
  - Automatic agent attribution
  - Changes summary formatting
  - Draft PR support
  - Label management
  - Integration with GitHub Copilot, Claude Code, Gemini Code

### 14. **CLI Tools** (NEW)
- **GitHub CLI**: GitHub command-line integration
- **Claude CLI**: Claude API access
- **Gemini CLI**: Gemini API access
- **VSCode CLI**: VSCode automation
- Status checking and installation for all CLIs

### 15. **Code Analysis**
- Pre-PR code analysis
- Security pattern detection
- Test coverage recommendations
- Linting integration

## Dashboard Access

**URL**: `http://localhost:8899/mcp/software`

## Navigation Structure

The dashboard features a comprehensive sidebar with 15 sections:

1. **Overview** - System status and tool cards
2. **Repository** - GitHub repository ingestion
3. **CI/CD** - Workflow analysis
4. **Logs** - Log parsing (systemd/k8s)
5. **Dependencies** - Dependency analysis
6. **Workflows** - DAG planning
7. **Resources** - GPU prediction
8. **Healing** - Auto-healing coordination
9. **Theorems** - Logic rule browser
10. **Testing** - Test generation and running
11. **Linting** - Code quality checking
12. **Documentation** - Doc generation
13. **Codebase Search** - Pattern finding
14. **PR Creation** - AI agent PRs
15. **CLI Tools** - CLI management

## Tool Access Methods

All tools are accessible via multiple methods:

### 1. MCP Tool Endpoints
```bash
POST /api/mcp/tools/software_engineering_tools/{tool_name}/execute
POST /api/mcp/tools/development_tools/{tool_name}/execute
```

### 2. Dashboard API
```bash
POST /api/mcp/software/*
```

### 3. JavaScript MCP SDK
```javascript
const mcpClient = new MCPClient('/api/mcp');
const result = await mcpClient.executeTool(
    'software_engineering_tools',
    'tool_name',
    parameters
);
```

### 4. Python Package Imports
```python
from ipfs_datasets_py import (
    # Software Engineering Tools
    scrape_github_repository,
    analyze_github_actions,
    parse_systemd_logs,
    parse_kubernetes_logs,
    analyze_dependency_chain,
    create_workflow_dag,
    predict_gpu_needs,
    detect_error_patterns,
    coordinate_auto_healing,
    list_software_theorems,
    create_ai_agent_pr,
    
    # Development Tools
    test_generator,
    run_comprehensive_tests,
    lint_python_codebase,
    documentation_generator,
    codebase_search
)
```

## Usage Examples

### Test Generation
```python
# Via Python
from ipfs_datasets_py.mcp_server.tools.development_tools.test_generator import test_generator

result = test_generator(
    file_path="my_module.py",
    test_framework="pytest"
)

# Via MCP SDK
const result = await mcpClient.executeTool(
    'development_tools',
    'test_generator',
    {file_path: 'my_module.py', test_framework: 'pytest'}
);
```

### Code Linting
```python
# Via Python
from ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools import lint_python_codebase

result = lint_python_codebase(
    path=".",
    fix_issues=True,
    files=["module.py"]
)

# Via MCP SDK
const result = await mcpClient.executeTool(
    'development_tools',
    'lint_python_codebase',
    {path: '.', fix_issues: true, files: ['module.py']}
);
```

### Documentation Generation
```python
# Via Python
from ipfs_datasets_py.mcp_server.tools.development_tools.documentation_generator import documentation_generator

result = documentation_generator(
    input_path="src/",
    output_path="docs/",
    format="markdown"
)

# Via MCP SDK
const result = await mcpClient.executeTool(
    'development_tools',
    'documentation_generator',
    {input_path: 'src/', output_path: 'docs/', format: 'markdown'}
);
```

### Codebase Search
```python
# Via Python
from ipfs_datasets_py.mcp_server.tools.development_tools.codebase_search import codebase_search

result = codebase_search(
    pattern="def my_function",
    path=".",
    use_regex=False,
    case_sensitive=True
)

# Via MCP SDK
const result = await mcpClient.executeTool(
    'development_tools',
    'codebase_search',
    {pattern: 'def my_function', path: '.', use_regex: false, case_sensitive: true}
);
```

### AI Agent PR Creation
```python
# Via Python
from ipfs_datasets_py.mcp_server.tools.software_engineering_tools.ai_agent_pr_creator import create_ai_agent_pr

result = create_ai_agent_pr(
    owner="myorg",
    repo="myrepo",
    branch_name="copilot/feature",
    title="Add feature",
    description="Feature description",
    changes_summary=[
        {"file": "new_file.py", "action": "added", "description": "New module"}
    ],
    agent_name="GitHub Copilot",
    draft=False
)

# Via MCP SDK
const result = await mcpClient.executeTool(
    'software_engineering_tools',
    'create_ai_agent_pr',
    {owner: 'myorg', repo: 'myrepo', branch_name: 'copilot/feature', ...}
);
```

### CLI Tool Management
```python
# Check GitHub CLI status
from ipfs_datasets_py.mcp_server.tools.development_tools.github_cli_server_tools import github_cli_status

status = github_cli_status()
print(f"Installed: {status['status']['installed']}")

# Install Claude CLI
from ipfs_datasets_py.mcp_server.tools.development_tools.claude_cli_server_tools import claude_cli_install

result = claude_cli_install(force=False)
```

## Complete Workflow Example

```python
from ipfs_datasets_py.mcp_server.tools.software_engineering_tools.ai_agent_pr_creator import (
    analyze_code_for_pr,
    create_ai_agent_pr
)
from ipfs_datasets_py.mcp_server.tools.development_tools.test_generator import test_generator
from ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools import lint_python_codebase

# 1. Generate tests for new code
test_result = test_generator(
    file_path="new_feature.py",
    test_framework="pytest"
)

# 2. Lint the code
lint_result = lint_python_codebase(
    path=".",
    fix_issues=True,
    files=["new_feature.py", "test_new_feature.py"]
)

# 3. Analyze code for PR
analysis = analyze_code_for_pr(
    file_paths=["new_feature.py", "test_new_feature.py"],
    analysis_type="comprehensive"
)

# 4. Create AI agent PR
if not analysis['issues']:
    pr_result = create_ai_agent_pr(
        owner="myorg",
        repo="myrepo",
        branch_name="copilot/new-feature",
        title="Add new feature with tests",
        description="Implements new feature with comprehensive testing",
        changes_summary=[
            {"file": "new_feature.py", "action": "added", "description": "New feature module"},
            {"file": "test_new_feature.py", "action": "added", "description": "Comprehensive tests"}
        ],
        agent_name="GitHub Copilot",
        labels=["ai-generated", "tested", "enhancement"]
    )
    
    print(f"PR created: {pr_result['pr_url']}")
```

## Integration with AI Coding Assistants

The unified tools suite seamlessly integrates with:

- **GitHub Copilot**: Full workflow automation
- **Claude Code**: MCP server integration
- **Gemini Code**: API-based workflows
- **Custom AI Agents**: Extensible architecture

## Benefits

1. **Unified Interface**: All tools in one dashboard
2. **Consistent API**: Same patterns across all tools
3. **MCP Integration**: Full MCP server support
4. **Multiple Access Methods**: Dashboard, API, SDK, Python
5. **AI Agent Ready**: Built for AI coding assistants
6. **Comprehensive Coverage**: 15 tool categories
7. **Professional UI**: Clean, modern interface
8. **Real-time Feedback**: Loading indicators and results
9. **Error Handling**: Comprehensive error messages
10. **Extensible**: Easy to add new tools

## Architecture

```
Software Engineering Dashboard
├── Frontend (HTML/JS)
│   ├── Navigation (15 sections)
│   ├── Forms (tool inputs)
│   ├── MCP SDK integration
│   └── Results display
├── Backend (Flask/Python)
│   ├── Dashboard routes
│   ├── API endpoints
│   └── Tool execution
├── Tools (Python)
│   ├── software_engineering_tools/
│   │   ├── github_repository_scraper.py
│   │   ├── github_actions_analyzer.py
│   │   ├── systemd_log_parser.py
│   │   ├── kubernetes_log_analyzer.py
│   │   ├── dependency_chain_analyzer.py
│   │   ├── dag_workflow_planner.py
│   │   ├── gpu_provisioning_predictor.py
│   │   ├── error_pattern_detector.py
│   │   ├── auto_healing_coordinator.py
│   │   ├── software_theorems.py
│   │   └── ai_agent_pr_creator.py
│   └── development_tools/
│       ├── test_generator.py
│       ├── test_runner.py
│       ├── linting_tools.py
│       ├── documentation_generator.py
│       ├── codebase_search.py
│       ├── github_cli_server_tools.py
│       ├── claude_cli_server_tools.py
│       ├── gemini_cli_server_tools.py
│       └── vscode_cli_tools.py
└── MCP Server
    ├── Tool registration
    ├── Tool discovery
    └── Tool execution
```

## Future Enhancements

- Real-time log streaming
- Interactive dependency graphs
- Advanced workflow visualizations
- More AI agent integrations
- Enhanced code analysis
- Performance profiling tools
- Security scanning integration
- Automated refactoring tools

## Support

For issues or questions:
- Check tool documentation in respective files
- Review `AI_AGENT_PR_INTEGRATION.md` for PR creation
- Review `SOFTWARE_DASHBOARD_IMPLEMENTATION.md` for implementation details
- Use the dashboard's built-in help tooltips
