# IPFS Datasets CLI Installation Guide

This guide will help you install the `ipfs-datasets` CLI tool properly so it's available system-wide.

## Installation Steps

1. **Install the package in development mode** (recommended for development):
   ```bash
   pip install -e .
   ```

2. **Or install from the repository**:
   ```bash
   pip install .
   ```

3. **Or install directly from GitHub**:
   ```bash
   pip install git+https://github.com/endomorphosis/ipfs_datasets_py.git
   ```

## Verification

After installation, you should be able to run:

```bash
# Check if the CLI is installed
ipfs-datasets --help
ipfs-datasets-cli --help

# Get system status
ipfs-datasets info status

# List available tools
ipfs-datasets tools categories
```

## Troubleshooting

### CLI Not Found After Installation

If the `ipfs-datasets` command is not found after installation:

1. **Check if the package is installed**:
   ```bash
   pip list | grep ipfs-datasets
   ```

2. **Check your PATH**:
   ```bash
   echo $PATH
   ```

3. **Find where pip installs scripts**:
   ```bash
   python -m site --user-base
   # The scripts will be in {user-base}/bin
   ```

4. **Add the scripts directory to your PATH** if needed:
   ```bash
   export PATH="$HOME/.local/bin:$PATH"
   # Add this to your ~/.bashrc or ~/.zshrc for persistence
   ```

### Virtual Environment Issues

If you're using a virtual environment:

1. **Make sure it's activated**:
   ```bash
   source .venv/bin/activate  # or your venv path
   ```

2. **Install in the virtual environment**:
   ```bash
   pip install -e .
   ```

3. **Verify the CLI is available**:
   ```bash
   which ipfs-datasets
   ipfs-datasets --help
   ```

## Alternative: Direct Script Execution

If installation doesn't work, you can always run the CLI directly:

```bash
# From the repository root
python ipfs_datasets_cli.py --help
python ipfs_datasets_cli.py info status

# Or use the bash wrapper
./ipfs-datasets --help
```

## Features Available

Once installed, you can use:

- **System Information**: `ipfs-datasets info status`
- **Tool Discovery**: `ipfs-datasets tools categories`
- **MCP Server Management**: `ipfs-datasets mcp start`
- **Dataset Operations**: `ipfs-datasets dataset load squad`
- **Vector Operations**: `ipfs-datasets vector create data.txt`
- **IPFS Operations**: `ipfs-datasets ipfs pin "Hello World"`

## Support

If you continue to have issues:

1. Check that you have Python 3.10+ installed
2. Ensure pip is up to date: `pip install --upgrade pip`
3. Try installing in a fresh virtual environment
4. Check the repository issues for similar problems

The CLI tool provides comprehensive help with `ipfs-datasets --help` and detailed usage examples.