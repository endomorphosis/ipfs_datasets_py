# Development Tools for IPFS Datasets

This document provides an overview of the development tools integrated into the IPFS Datasets MCP server. These tools were migrated from the claudes_toolbox project and enhanced for IPFS dataset awareness.

## Available Tools

The development tools suite includes the following tools:

### 1. Codebase Search Tool (`codebase_search`)

A powerful search tool for finding patterns in code.

**Features:**
- Regular expression support
- File filtering by extension
- Recursive directory scanning
- Configurable output formats (text, JSON, markdown)
- IPFS-aware pattern matching

**Usage Example:**
```python
from ipfs_datasets_py.mcp_server.tools.development_tools.codebase_search import codebase_search

results = codebase_search(
    pattern="def my_function",
    path="./src",
    max_depth=3,
    format="json",
    regex=True
)
```

**VS Code Copilot Chat Usage:**
```
Use the codebase_search tool to find all functions with "dataset" in their name
```

### 2. Documentation Generator (`documentation_generator`)

Generates comprehensive documentation from source code.

**Features:**
- Multiple output formats (markdown, HTML)
- Docstring analysis and extraction
- Class hierarchy visualization
- Template-based rendering
- Support for various docstring formats

**Usage Example:**
```python
from ipfs_datasets_py.mcp_server.tools.development_tools.documentation_generator import documentation_generator

docs = documentation_generator(
    input_path="./src/my_module.py",
    format_type="markdown"
)
```

**VS Code Copilot Chat Usage:**
```
Use the documentation_generator tool to create markdown docs for server.py
```

### 3. Linting Tools (`lint_python_codebase`)

Comprehensive code analysis and linting for Python codebases.

**Features:**
- Integration with flake8, mypy, black, isort
- Customizable rule sets
- Support for ignoring specific rules
- Detailed issue reporting
- Dataset-specific linting rules

**Usage Example:**
```python
from ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools import lint_python_codebase

lint_results = lint_python_codebase(
    path="./src",
    fix=False
)
```

**VS Code Copilot Chat Usage:**
```
Use the lint_python_codebase tool to check for issues in my_file.py
```

### 4. Test Generator (`test_generator`)

Automatically generates test files for Python code.

**Features:**
- Support for pytest and unittest frameworks
- Test function generation based on source analysis
- Mock generation for dependencies
- Dataset-aware test case generation
- Parametrized test support

**Usage Example:**
```python
from ipfs_datasets_py.mcp_server.tools.development_tools.test_generator import test_generator

# Create test specification
test_spec = {
    "name": "test_module",
    "test_class": "TestModule",
    "tests": [
        {
            "name": "test_function",
            "description": "Test the main function",
            "assertions": ["assert result == expected"]
        }
    ]
}

test_code = test_generator(
    name="test_my_module",
    description="Tests for my_module.py",
    test_specification=json.dumps(test_spec),
    harness="pytest"
)
```

**VS Code Copilot Chat Usage:**
```
Use the test_generator tool to create pytest tests for my_file.py
```

### 5. Test Runner (`run_comprehensive_tests`)

Executes and reports on test suites with detailed analysis.

**Features:**
- Support for multiple test frameworks
- Coverage reporting
- Parallel test execution
- XML/JSON/HTML report generation
- Integration with CI systems

**Usage Example:**
```python
from ipfs_datasets_py.mcp_server.tools.development_tools.test_runner import run_comprehensive_tests

test_results = run_comprehensive_tests(
    path="./tests",
    run_unit_tests=True,
    run_type_check=True,
    run_linting=True,
    test_framework="pytest",
    coverage=True,
    output_formats=["json", "markdown"]
)
```

**VS Code Copilot Chat Usage:**
```
Use the run_comprehensive_tests tool to execute all tests in the project
```

## Configuration

The development tools can be configured through environment variables:

- `DEVELOPMENT_TOOLS_ENABLED`: Set to "true" to enable development tools (default: "true")
- `DEVELOPMENT_TOOLS_LOG_LEVEL`: Log level for development tools (default: "INFO")
- `DEVELOPMENT_TOOLS_CONFIG_PATH`: Path to a custom configuration file

Additionally, you can configure the tools through the `.vscode/mcp_settings.json` file for VS Code integration:

```json
{
  "mcpServers": {
    "ipfs_datasets": {
      "command": "python",
      "args": ["-m", "ipfs_datasets_py.mcp_server"],
      "env": {
        "PYTHONPATH": "/path/to/ipfs_datasets_py",
        "DEVELOPMENT_TOOLS_ENABLED": "true",
        "LOG_LEVEL": "DEBUG"
      }
    }
  }
}
```

## VS Code Integration

The development tools are designed to work seamlessly with VS Code through the Copilot Chat interface. To use them:

1. Ensure the IPFS Datasets MCP server is running
2. Open VS Code with the Copilot Chat extension
3. Ask Copilot Chat to use a specific tool (see examples above)

For detailed setup and testing instructions, see [VSCODE_INTEGRATION_TESTING.md](./VSCODE_INTEGRATION_TESTING.md).

## Performance Considerations

The development tools are designed for efficiency, but may require significant resources when processing large codebases. For optimal performance:

1. Use specific paths rather than scanning entire projects
2. Limit search depth for large directory structures
3. Use the performance profiling tools to identify bottlenecks

## Error Handling

The development tools include comprehensive error handling. Common issues include:

- Path not found errors: Ensure file paths are correct and accessible
- Import errors: Check that required dependencies are installed
- Permission errors: Verify file permissions for read/write operations

Detailed logs are available in the MCP server output.

## Future Enhancements (Phase 2)

In Phase 2, these tools will be enhanced with:

- IPFS-aware code analysis
- Dataset integration features
- Distributed testing capabilities
- Enhanced visualization of results

See [PHASE2_PLANNING.md](./PHASE2_PLANNING.md) for more details.

## Testing and Validation

The development tools include comprehensive tests. To run individual tool tests:

```bash
python test_individual_tools.py
```

For VS Code integration testing:

```bash
python vscode_integration_test.py
```

## Support and Feedback

For issues, questions, or feedback related to the development tools, please:

1. Check the logs for error messages
2. Refer to the documentation in this README
3. Submit detailed bug reports with steps to reproduce

---

*This documentation was generated and last updated on May 27, 2025.*
