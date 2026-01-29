# CLI Tools

This directory contains alternative CLI interfaces for the ipfs_datasets_py package.

## Main CLI

The primary CLI tool is `ipfs-datasets` (or `ipfs_datasets_cli.py` in the root directory).

## Alternative CLI Tools

### mcp_cli.py
Model Context Protocol CLI interface for interacting with MCP servers and tools.

**Usage:**
```bash
python scripts/cli/mcp_cli.py [command] [options]
```

### enhanced_cli.py (DEPRECATED)
Enhanced CLI with dynamic tool discovery. **Functionality has been merged into the main `ipfs-datasets` CLI.**

**Migration:**
```bash
# Old
python enhanced_cli.py --list-categories

# New
ipfs-datasets tools categories
```

See `CLI_TOOL_MERGE.md` in the root directory for complete migration guide.

### integrated_cli.py
Integrated CLI with additional features for advanced workflows.

**Usage:**
```bash
python scripts/cli/integrated_cli.py [command] [options]
```

### comprehensive_distributed_cli.py
CLI for distributed operations across multiple nodes.

**Usage:**
```bash
python scripts/cli/comprehensive_distributed_cli.py [command] [options]
```

## Recommendation

For most use cases, use the main `ipfs-datasets` CLI tool in the root directory, which provides:
- All core functionality
- Dynamic tool discovery (100+ tools)
- Consistent interface
- Better documentation
- Active maintenance
