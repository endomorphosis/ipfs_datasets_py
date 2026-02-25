# Lizardpersons Function Tools

This directory contains utility and prototyping infrastructure originally built to
support function-based tool wrapping for the legacy lizardperson CLI programs.

## Active Sub-directories

| Directory | Contents | Purpose |
|---|---|---|
| `meta_tools/` | `list_tools_in_cli_dir.py`, `list_tools_in_functions_dir.py`, `use_cli_program_as_tool.py`, `use_function_as_tool.py` | Runtime introspection helpers — load any function/CLI from a directory as an MCP tool |
| `prototyping_tools/` | `json_to_pydantic.py`, `json_to_python_file.py`, `python_file_to_json.py` | Code-generation utilities: JSON ↔ Pydantic model, JSON ↔ Python file |
| `llm_context_tools/` | `get_current_time.py` | LLM context helpers — time utilities |
| `cli/` | *(empty — placeholder scripts removed)* | Reserved for CLI-wrapper stub tools |
| `functions/` | *(empty — placeholder scripts removed)* | Reserved for function-wrapper stub tools |

## Usage

The `meta_tools/` sub-directory provides helpers that can dynamically load any Python function
or CLI program from a directory and expose it as an MCP-compatible tool call:

```python
from ipfs_datasets_py.mcp_server.tools.lizardpersons_function_tools.meta_tools.use_function_as_tool import (
    _call_function_and_return_results,
)

result = _call_function_and_return_results(
    function_name="my_func",
    function=my_func,
    args_dict={"arg1": "value"},
)
```

## Notes

- Empty placeholder files (`sample_tool.py`, `test_program_name.py`, `test_function_name.py`)
  were removed as they contained no real implementation.
- New function-based tools should be placed in the appropriate category directory.

