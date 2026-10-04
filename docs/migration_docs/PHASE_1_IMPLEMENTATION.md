# Phase 1 Implementation Guide
## Foundation & Preparation for claudes_toolbox Migration

This guide provides step-by-step instructions for implementing Phase 1 of the claudes_toolbox migration roadmap.

## Step 1: Create Development Tools Directory Structure

### Create the directory structure:
```bash
mkdir -p ipfs_datasets_py/mcp_server/tools/development_tools
```

### Create initial files:
- `__init__.py` - Module initialization
- `base_tool.py` - Base class for development tools
- `config.py` - Configuration management
- `error_handling.py` - Error handling utilities

## Step 2: Update Dependencies

### Merge dependencies from claudes_toolbox into main pyproject.toml:
Add to the main project's dependencies:
- `coverage>=7.8.0` - Test coverage analysis
- `flake8>=7.2.0` - Python linting  
- `mypy>=1.15.0` - Type checking
- `jinja2>=3.1.6` - Template generation
- `anthropic>=0.50.0` - LLM API access (optional)
- `openai>=1.76.0` - LLM API access (optional)
- `psutil>=7.0.0` - System utilities
- `pyyaml>=6.0.2` - YAML parsing

## Step 3: Create Base Infrastructure Files

This step will create the foundational files needed for development tools.

## Step 4: Test the Infrastructure

Create a simple test tool to validate the infrastructure works correctly.

## Step 5: Update MCP Server Registration

Modify the main MCP server to discover and register development tools.

---

## Implementation Commands

Run these commands to execute Phase 1:

```bash
# 1. Create directory structure
mkdir -p ipfs_datasets_py/mcp_server/tools/development_tools

# 2. Install additional dependencies
pip install coverage flake8 mypy jinja2 psutil pyyaml

# 3. Create and test infrastructure (files will be created by the implementation)

# 4. Run tests to validate setup
python -m pytest ipfs_datasets_py/mcp_server/tools/development_tools/tests/
```

---

## Success Criteria for Phase 1

- ✅ Directory structure created
- ✅ Dependencies updated and installed
- ✅ Base infrastructure files created
- ✅ Simple test tool working
- ✅ MCP server can discover development tools
- ✅ VS Code tasks updated for development tool testing

Once Phase 1 is complete, we can proceed to Phase 2 (Core Tool Migration).
