# IPFS Datasets CLI - Quick Start Guide

## ⚡ Quick Solution for CLI Access

The `ipfs-datasets` CLI tool is ready to use! Here are the fastest ways to get it working:

### Option 1: Direct Script Execution (Immediate)
```bash
# Navigate to the repository
cd /path/to/ipfs_datasets_py

# Run the CLI directly
python ipfs_datasets_cli.py --help
python ipfs_datasets_cli.py info status
python ipfs_datasets_cli.py tools categories
```

### Option 2: Bash Wrapper (Convenient)
```bash
# Make the wrapper executable (if needed)
chmod +x ipfs-datasets

# Use the wrapper
./ipfs-datasets --help
./ipfs-datasets info status
./ipfs-datasets mcp start
```

### Option 3: System-wide Installation (Recommended)
```bash
# Install in development mode for easy updates
pip install -e .

# Now you can use from anywhere
ipfs-datasets --help
ipfs-datasets info status
ipfs-datasets tools categories
ipfs-datasets mcp start
```

## 🚀 Available Commands

Once you have CLI access, try these commands:

### System Information
```bash
ipfs-datasets info status              # System status and available tools
ipfs-datasets tools categories         # List all tool categories
ipfs-datasets tools list dataset_tools # List tools in a category
```

### MCP Server Management
```bash
ipfs-datasets mcp start               # Start both server and dashboard
ipfs-datasets mcp status              # Check service status
ipfs-datasets mcp stop                # Stop all services
ipfs-datasets mcp start-server        # Start just the MCP server
ipfs-datasets mcp start-dashboard     # Start just the web dashboard
```

### Tool Execution
```bash
# Execute tools dynamically
ipfs-datasets tools execute dataset_tools load_dataset --source "squad" --format json
ipfs-datasets tools execute vector_tools create_vector_index --dimension 768
```

### Dataset Operations
```bash
ipfs-datasets dataset load squad                    # Load a HuggingFace dataset
ipfs-datasets dataset convert data.json csv output.csv  # Convert formats
```

### IPFS Operations
```bash
ipfs-datasets ipfs pin "Hello, IPFS!"              # Pin data to IPFS
ipfs-datasets ipfs get QmHash123...                 # Get data by hash
```

## 🔧 Troubleshooting

### CLI Not Found After Installation
If `ipfs-datasets` command is not found after `pip install -e .`:

1. **Check your PATH**:
   ```bash
   echo $PATH
   python -m site --user-base
   ```

2. **Add to PATH if needed**:
   ```bash
   export PATH="$HOME/.local/bin:$PATH"
   # Add to ~/.bashrc for persistence
   ```

3. **Use direct execution as fallback**:
   ```bash
   python ipfs_datasets_cli.py info status
   ```

### Virtual Environment Issues
```bash
# Create fresh venv
python -m venv .venv
source .venv/bin/activate

# Install and test
pip install -e .
ipfs-datasets --help
```

### Missing Dependencies
The CLI works with minimal dependencies. If you get import errors:

```bash
# Install core dependencies
pip install flask pyyaml

# For full functionality
pip install -e .[all]
```

## 📁 What We Fixed

The CLI wasn't available because the package setup was missing console script entry points. We added:

**In `setup.py`:**
```python
entry_points={
    'console_scripts': [
        'ipfs-datasets=ipfs_datasets_cli:cli_main',
        'ipfs-datasets-cli=ipfs_datasets_cli:cli_main',
    ],
}
```

**In `pyproject.toml`:**
```toml
[project.scripts]
ipfs-datasets = "ipfs_datasets_cli:cli_main"
ipfs-datasets-cli = "ipfs_datasets_cli:cli_main"
```

**In `ipfs_datasets_cli.py`:**
```python
def cli_main():
    """Entry point wrapper for console scripts."""
    import asyncio
    asyncio.run(main())
```

## 🎯 Next Steps

1. **Test the CLI**: `ipfs-datasets info status`
2. **Start MCP Services**: `ipfs-datasets mcp start`
3. **Access Dashboard**: Visit `http://localhost:8080/mcp`
4. **Explore Tools**: `ipfs-datasets tools categories`

The CLI is now properly configured and ready to use!