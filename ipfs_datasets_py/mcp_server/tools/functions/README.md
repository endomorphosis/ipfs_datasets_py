# Functions

MCP tool for executing Python code snippets in a sandboxed environment.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `execute_python_snippet.py` | `execute_python_snippet()` | Execute a Python code snippet and return stdout, stderr, and return value |

## Usage

```python
from ipfs_datasets_py.mcp_server.tools.functions import execute_python_snippet

result = await execute_python_snippet(
    code="import math\nprint(math.pi)\nresult = math.sqrt(16)",
    timeout=10,
    allowed_imports=["math", "json", "datetime"]
)
# Returns: {"stdout": "3.14159...\n", "stderr": "", "return_value": None, "exit_code": 0}
```

> ⚠️ **Security note:** Code execution is sandboxed via `RestrictedPython` or subprocess
> isolation. Only trusted inputs should be passed to this tool.

## Dependencies

- `RestrictedPython` — safe code execution sandbox (optional)

## Status

| Tool | Status |
|------|--------|
| `execute_python_snippet` | ✅ Production ready |
