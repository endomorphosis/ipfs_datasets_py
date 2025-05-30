# VS Code Copilot Chat Integration Testing Guide

## Overview

This guide provides instructions for testing the development tools integration with VS Code Copilot Chat. These tools have been migrated from claudes_toolbox and integrated into the IPFS datasets MCP server.

## Prerequisites

- VS Code with Copilot Chat extension installed and configured
- IPFS datasets MCP server installed and running
- VS Code MCP extension configured to connect to the IPFS datasets MCP server

## Setup

1. Make sure the `.vscode/mcp_settings.json` file is properly configured:
   ```json
   {
     "mcpServers": {
       "ipfs_datasets": {
         "command": "python",
         "args": ["-m", "ipfs_datasets_py.mcp_server"],
         "env": {
           "PYTHONPATH": "/home/barberb/ipfs_datasets_py"
         }
       }
     }
   }
   ```

2. Start the MCP server in a terminal:
   ```bash
   cd /home/barberb/ipfs_datasets_py
   python -m ipfs_datasets_py.mcp_server
   ```

3. Verify the server is running by looking for output similar to:
   ```
   INFO:ipfs_datasets_py.mcp_server.server:Registered 15 tools with the MCP server
   INFO:root:Starting server at http://localhost:8080
   ```

## Test Case 1: Codebase Search

1. In VS Code Copilot Chat, type the following query:
   ```
   Use the codebase_search tool to find all functions with "test" in their name in the current project.
   ```

2. Expected result:
   - Copilot Chat should invoke the codebase_search tool
   - Tool should return a list of functions with "test" in their name
   - Results should be displayed in a formatted way in the chat

3. Check for:
   - Tool invocation message 
   - Correct formatting of search results
   - No errors in the MCP server terminal

## Test Case 2: Documentation Generation

1. Create or identify a Python file to document (e.g., `test_individual_tools.py`)

2. In VS Code Copilot Chat, type the following query:
   ```
   Use the documentation_generator tool with input_path="test_individual_tools.py" and format_type="markdown"
   ```

3. Expected result:
   - Copilot Chat should invoke the documentation_generator tool
   - Tool should generate markdown documentation
   - Documentation should include classes, methods, and docstrings

4. Check for:
   - Proper formatting of the documentation
   - Inclusion of all classes and methods from the file
   - No errors in the MCP server terminal

## Test Case 3: Linting Tools

1. In VS Code Copilot Chat, type the following query:
   ```
   Use the lint_python_codebase tool with path="test_individual_tools.py", fix_issues=False, and dry_run=True
   ```

2. Expected result:
   - Copilot Chat should invoke the lint_python_codebase tool
   - Tool should return linting results
   - Results should highlight any code issues found

3. Check for:
   - Properly formatted lint results
   - Categorization of issues (errors, warnings)
   - No errors in the MCP server terminal

## Test Case 4: Test Generator

1. In VS Code Copilot Chat, type the following query:
   ```
   Use the test_generator tool to create a test with name="test_tools", description="Tests for tools", and harness="pytest", with a test specification that tests the ToolTester class in test_individual_tools.py
   ```

2. Expected result:
   - Copilot Chat should invoke the test_generator tool
   - Tool should generate pytest test code
   - Generated code should include tests for the ToolTester class

3. Check for:
   - Proper test class structure
   - Test methods for each public method in the source file
   - No errors in the MCP server terminal

## Test Case 5: Comprehensive Test Runner

1. In VS Code Copilot Chat, type the following query:
   ```
   Use the run_comprehensive_tests tool with path=".", run_unit_tests=True, run_linting=False, run_type_check=False, test_framework="pytest", and verbose=True
   ```

2. Expected result:
   - Copilot Chat should invoke the run_comprehensive_tests tool
   - Tool should execute tests and return results
   - Results should include test statistics (passed/failed)

3. Check for:
   - Summary of test results
   - Proper formatting of test output
   - No errors in the MCP server terminal

## Recording Results

After completing each test, record the results in the `vscode_integration_results.md` file. For each tool, indicate:

- ✅ Working correctly
- ⚠️ Partially working (explain issues)
- ❌ Not working (explain issues)

Also note any observations about:
- Response time
- User experience
- Quality of results
- Any unexpected behavior

## Troubleshooting

If issues are encountered:

1. Check the MCP server terminal for error messages
2. Verify the tool is properly registered with the server
3. Ensure the VS Code MCP settings are correctly configured
4. Try restarting the MCP server and VS Code
5. Use the `test_individual_tools.py` script to test tools directly

## Next Steps

After completing the integration testing:

1. Address any issues found
2. Update the `PHASE1_COMPLETE.md` document with test results
3. Proceed with performance optimization testing
4. Begin preparation for Phase 2 implementation
