# MCP Server Quick Start Guide

**Date:** 2026-02-20  
**Status:** ✅ Production Ready — All 7 refactoring phases complete  
**Audience:** New contributors, developers integrating the MCP server

---

## 🎯 Overview

The IPFS Datasets MCP Server exposes 382 tools across 60 categories through the Model Context Protocol. It features:
- **Dual-runtime architecture** — FastAPI (general tools) + Trio (P2P tools)
- **Hierarchical tool system** — 99% context reduction (382 tools → 4 meta-tools)
- **Thin wrapper pattern** — all business logic in core modules
- **853 tests** passing with 85-90% coverage

---

## 📁 Key Documents

| Document | Purpose |
|----------|---------|
| [README.md](README.md) | Project overview and feature list |
| [THIN_TOOL_ARCHITECTURE.md](THIN_TOOL_ARCHITECTURE.md) | Architecture principles (start here!) |
| [PHASES_STATUS.md](PHASES_STATUS.md) | All 7 phases complete with metrics |
| [MASTER_IMPROVEMENT_PLAN_2026_v5.md](MASTER_IMPROVEMENT_PLAN_2026_v5.md) | Next-generation improvement areas |
| [SECURITY.md](SECURITY.md) | Security hardening details |
| [docs/architecture/](docs/architecture/) | Dual-runtime and MCP++ design |
| [docs/development/](docs/development/) | Tool development guide |

---

## 🏗️ Architecture Overview

```
User
 │
 ▼
HierarchicalToolManager   ← 4 meta-tools (list, schema, dispatch)
 │                            exposes all 382 tools lazily
 ▼
RuntimeRouter             ← routes to correct async runtime
 ├── FastAPI Runtime  ──→  general tools (datasets, search, graph, …)
 └── Trio Runtime     ──→  P2P tools (workflow, task queue, peers)
```

### Core Files

| File | Purpose | Lines |
|------|---------|-------|
| `server.py` | Main MCP server (FastMCP) | ~1,000 |
| `hierarchical_tool_manager.py` | Lazy category registry | ~560 |
| `fastapi_service.py` | REST API runtime | ~1,420 |
| `runtime_router.py` | Dual-runtime dispatch | ~950 |
| `p2p_service_manager.py` | P2P + MCP++ integration | ~420 |
| `tool_registry.py` | Tool loading and registration | ~1,200 |
| `monitoring.py` | Metrics and observability | ~1,750 |
| `validators.py` | Input validation | ~1,000 |
| `exceptions.py` | 18 custom exception classes | ~250 |

---

## 🚀 Getting Started

### Prerequisites

```bash
# Python 3.12+
python --version

# Clone the repo
git clone https://github.com/endomorphosis/ipfs_datasets_py.git
cd ipfs_datasets_py
```

### Install Dependencies

```bash
# Install base + dev dependencies
pip install -e ".[dev,test]"

# Verify MCP server import
python -c "from ipfs_datasets_py.mcp_server import server; print('OK')"
```

### Run the Server

```bash
# Main server (FastMCP)
python -m ipfs_datasets_py.mcp_server

# Standalone server
python ipfs_datasets_py/mcp_server/standalone_server.py

# Simple server (lightweight, no P2P)
python ipfs_datasets_py/mcp_server/simple_server.py
```

### Explore the Tool System

```python
from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager

manager = HierarchicalToolManager()
manager.discover_tools()

# List all categories
categories = manager.list_categories()
print(categories)  # ['dataset_tools', 'search_tools', ...]

# List tools in a category
tools = manager.list_tools("dataset_tools")
print(tools)

# Get a tool schema
schema = manager.get_tool_schema("dataset_tools", "load_dataset")
print(schema)

# Execute a tool
result = manager.dispatch("dataset_tools", "load_dataset", {"source": "squad"})
```

---

## 🧪 Running Tests

```bash
# All MCP tests
pytest tests/mcp/ -v

# Unit tests only (fast)
pytest tests/mcp/unit/ -v

# Integration tests
pytest tests/mcp/integration/ -v

# With coverage report
pytest tests/mcp/ --cov=ipfs_datasets_py.mcp_server --cov-report=html

# Specific component
pytest tests/mcp/unit/test_hierarchical_tool_manager.py -v
```

**Current results:** 853 passing, 38 skipped, 0 failing

---

## 🔧 Development Workflow

### Creating a New Tool

1. Read [THIN_TOOL_ARCHITECTURE.md](THIN_TOOL_ARCHITECTURE.md)
2. Use the template in [docs/development/tool-templates/](docs/development/tool-templates/)
3. Put business logic in the appropriate `ipfs_datasets_py/` core module
4. Create a thin wrapper in `tools/<category>/`
5. Write tests following the GIVEN-WHEN-THEN pattern
6. Register the tool in `tool_registry.py`

**Template:**
```python
"""Tool: [name] — [one line description]."""
from typing import Any
from ..exceptions import MCPServerError


async def my_tool(param: str) -> dict[str, Any]:
    """[One-line description].

    Args:
        param: Description of parameter.

    Returns:
        dict with 'status', 'result' keys.

    Raises:
        MCPServerError: If operation fails.
    """
    # THIN: import and delegate to core module
    from ipfs_datasets_py.core_operations import my_module

    try:
        result = await my_module.do_work(param)
        return {"status": "success", "result": result}
    except ValueError as exc:
        raise MCPServerError(f"Invalid input: {exc}") from exc
```

### Code Standards (All Enforced ✅)

- Functions **<100 lines** (logic-heavy code)
- **No bare** `except:` or `except Exception:` handlers
- **Comprehensive docstrings** on all public functions/classes
- **Type hints** on all parameters and return values
- Tests follow **GIVEN-WHEN-THEN** pattern

### Before Committing

```bash
# Run tests
pytest tests/mcp/ -v

# Type checking
mypy ipfs_datasets_py/mcp_server/

# Linting
flake8 ipfs_datasets_py/mcp_server/

# Check coverage (must not decrease)
pytest tests/mcp/ --cov=ipfs_datasets_py.mcp_server
```

---

## 🐛 Common Issues

### "Module not found" on import
```bash
pip install -e ".[dev,test]"
```

### Tests fail with "Trio not available"
```bash
pip install trio>=0.22.0
```

### FastAPI server SECRET_KEY error
```bash
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
```

### P2P features unavailable
This is expected when `ipfs_accelerate_py` is not installed. The server degrades gracefully with mock fallbacks.

---

## 📚 Additional Resources

- **MCP Specification:** https://spec.modelcontextprotocol.io/
- **IPFS Datasets:** https://github.com/endomorphosis/ipfs_datasets_py
- **Issues:** https://github.com/endomorphosis/ipfs_datasets_py/issues

---

**Guide Version:** 2.0  
**Last Updated:** 2026-02-20  
**Status:** ✅ Production Ready

