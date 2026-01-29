# CLI Tool Merge: scripts/cli/enhanced_cli.py → ipfs-datasets

## Summary

The functionality from `scripts/cli/enhanced_cli.py` has been successfully merged into the main `ipfs-datasets` CLI tool, providing a unified interface for all operations.

## Migration Guide

### Quick Reference

| Old Command (enhanced-cli) | New Command (ipfs-datasets) |
|---------------------------|----------------------------|
| `enhanced-cli --list-categories` | `ipfs-datasets tools categories` |
| `enhanced-cli --list-tools <cat>` | `ipfs-datasets tools list <cat>` |
| `enhanced-cli <cat> <tool> [args]` | `ipfs-datasets tools run <cat> <tool> [args]` |

### Detailed Examples

#### List All Tool Categories
```bash
# Old
enhanced-cli --list-categories

# New
ipfs-datasets tools categories

# Output includes tool counts
Available tool categories:
  dataset_tools (15 tools)
  ipfs_tools (8 tools)
  vector_tools (12 tools)
  pdf_tools (10 tools)
  ... etc
```

#### List Tools in a Category
```bash
# Old
enhanced-cli --list-tools dataset_tools

# New
ipfs-datasets tools list dataset_tools

# Output
Tools in 'dataset_tools':
  load_dataset: Load a dataset from various sources
  save_dataset: Save a dataset to storage
  convert_dataset_format: Convert between formats
  ... etc
```

#### Execute a Tool
```bash
# Old
enhanced-cli dataset_tools load_dataset --source squad --format json

# New
ipfs-datasets tools run dataset_tools load_dataset --source squad --format json

# Output (pretty by default)
✅ Success!
Dataset ID: squad
Summary:
  examples: 87,599
  format: json
  size: 45.2 MB
```

## New Features

### 1. Enhanced Tool Discovery

The main CLI now includes dynamic tool discovery:
- Scans `ipfs_datasets_py/mcp_server/tools/` at runtime
- Discovers all available tools automatically
- Shows tool counts per category
- Works offline (doesn't require MCP server)

### 2. Natural Argument Passing

```bash
# Simple arguments
ipfs-datasets tools run ipfs_tools get_from_ipfs --cid QmHash123

# Multiple arguments
ipfs-datasets tools run vector_tools search --query "text" --top_k 10

# JSON values (auto-detected)
ipfs-datasets tools run dataset_tools process --config '{"batch": 100}'

# Boolean flags
ipfs-datasets tools run analysis_tools analyze --verbose
```

### 3. Pretty Output

Results now have user-friendly formatting:
```
✅ Success!
Message: Operation completed
Result: Data processed successfully
```

Or for errors:
```
❌ Error!
Error: Invalid dataset source
```

### 4. JSON Output Option

Add `--json` for machine-readable output:
```bash
ipfs-datasets tools run dataset_tools load_dataset --source squad --json

# Output
{
  "status": "success",
  "dataset_id": "squad",
  "summary": {
    "examples": 87599,
    "format": "json",
    "size": "45.2 MB"
  }
}
```

### 5. Offline Operation

All tool commands work without MCP server:
- `tools categories` - Local directory scanning
- `tools list` - Local file enumeration  
- `tools run` - Direct function import and execution

### 6. Automatic Async Handling

The CLI automatically detects and handles async functions:
```python
# If tool function is async
async def my_tool(arg1, arg2):
    result = await some_operation()
    return result

# CLI handles it automatically
# No special flags needed
```

## Advantages of Merged CLI

### 1. Single Interface
- One command to learn: `ipfs-datasets`
- Consistent syntax across all operations
- No confusion between multiple CLI tools

### 2. Better Discovery
- See ALL available tools (100+)
- Tool counts per category
- Works offline

### 3. Easier Execution
- Natural `--arg value` syntax
- Auto JSON parsing
- Pretty output by default
- Better error messages

### 4. Improved UX
- ✅/❌ status indicators
- Human-readable formatting
- Progress indicators
- Helpful error messages

### 5. Backward Compatible
- All old commands still work
- `enhanced-cli.py` still functional (with deprecation warning)
- No breaking changes

## Architecture

### DynamicToolRunner Class

Located in `ipfs_datasets_cli.py`:
```python
class DynamicToolRunner:
    """Dynamically discover and run MCP tools."""
    
    def __init__(self):
        # Discovers tools in mcp_server/tools/
        self.discover_tools()
    
    def get_categories(self) -> List[str]:
        # Returns sorted list of categories
        
    def get_tools(self, category: str) -> List[str]:
        # Returns tools in a category
        
    async def run_tool(self, category, tool, **kwargs):
        # Executes a tool with given arguments
```

### Key Functions

```python
def print_result(result, format_type="pretty"):
    """Print results with ✅/❌ indicators"""

def parse_tool_args(args_list):
    """Parse CLI args into tool parameters"""
```

### Integration Points

1. **Tool Discovery** - Scans directory on demand
2. **Argument Parsing** - Natural CLI syntax → Python kwargs
3. **Function Execution** - Import, discover, filter args, execute
4. **Result Formatting** - Dict → Pretty or JSON output

## Testing

### Test Tool Discovery
```bash
ipfs-datasets tools categories
# Should list all tool categories with counts
```

### Test Tool Listing
```bash
ipfs-datasets tools list dataset_tools
# Should list all tools in dataset_tools category
```

### Test Tool Execution
```bash
# Simple test (may need dependencies)
ipfs-datasets tools run dataset_tools load_dataset --source squad

# Check error handling
ipfs-datasets tools run invalid_category test_tool
# Should show: ❌ Error! Category 'invalid_category' not found
```

## Deprecation Timeline

### Current (v1.0)
- ✅ Both tools work
- ⚠️ enhanced-cli shows deprecation warning
- ℹ️ Documentation updated

### Next Release (v1.1)
- ⚠️ enhanced-cli marked for removal
- ℹ️ Final migration warnings

### Future Release (v2.0)
- ❌ enhanced-cli removed
- ✅ Only ipfs-datasets remains

## Common Issues

### Issue: "No module named 'anyio'"
**Solution:** Install dependencies
```bash
pip install -r requirements.txt
# or
pip install -e .
```

### Issue: "Category not found"
**Solution:** Check spelling and available categories
```bash
ipfs-datasets tools categories
```

### Issue: "No callable functions found"
**Cause:** Tool file doesn't export functions properly
**Solution:** Check tool implementation or report issue

## Developer Notes

### Adding New Tools

Tools are automatically discovered if placed in:
```
ipfs_datasets_py/mcp_server/tools/<category>/<tool_name>.py
```

Requirements:
1. Must export at least one public function (no underscore prefix)
2. Function should accept keyword arguments
3. Function should return dict with at least `"status"` key
4. Can be sync or async (CLI handles both)

### Tool Function Pattern

```python
# Good tool function
async def my_tool(arg1: str, arg2: int = 10) -> dict:
    """Tool description."""
    try:
        result = await process(arg1, arg2)
        return {
            "status": "success",
            "result": result,
            "message": "Operation completed"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }
```

## Future Enhancements

### Planned
- [ ] Tab completion for categories and tools
- [ ] Interactive mode for tool execution
- [ ] Tool help text extraction
- [ ] Batch tool execution
- [ ] Tool aliases

### Considering
- [ ] Plugin system for external tools
- [ ] Tool versioning
- [ ] Tool dependencies checking
- [ ] Performance monitoring

## Support

### Questions?
- Check: `ipfs-datasets tools --help`
- Check: `ipfs-datasets tools run --help`
- See: Full documentation in docs/

### Report Issues
- GitHub Issues: https://github.com/endomorphosis/ipfs_datasets_py/issues
- Include: Command used, error message, expected behavior

## Summary

The merger provides:
- ✅ Unified CLI interface
- ✅ Better tool discovery
- ✅ Easier tool execution
- ✅ Improved user experience
- ✅ Offline functionality
- ✅ Backward compatibility

**Use `ipfs-datasets` for all operations going forward.**
