# VSCode CLI Integration

This document describes the VSCode CLI integration in the IPFS Datasets Python library.

## Overview

The VSCode CLI integration provides three ways to interact with the Visual Studio Code command-line interface:

1. **Python Module** - Direct programmatic access via `ipfs_datasets_py.utils.vscode_cli`
2. **CLI Command** - Access through the `ipfs-datasets` CLI tool
3. **MCP Tool** - Integration with the Model Context Protocol for AI assistant access

## Installation

The VSCode CLI integration is included in the IPFS Datasets Python package. No additional installation is required.

```bash
pip install ipfs-datasets-py
```

## Quick Start

### Download and Install VSCode CLI

```bash
# Using the CLI
ipfs-datasets vscode install

# Or with Python
from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI
cli = VSCodeCLI()
cli.download_and_install()
```

### Check Installation Status

```bash
# Using the CLI
ipfs-datasets vscode status

# Or with Python
from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI
cli = VSCodeCLI()
status = cli.get_status()
print(status)
```

## Python Module Usage

### Basic Usage

```python
from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI

# Initialize VSCode CLI manager
cli = VSCodeCLI()

# Check if installed
if not cli.is_installed():
    # Download and install
    cli.download_and_install()

# Get version
version = cli.get_version()
print(f"VSCode CLI Version: {version}")

# Execute a command
result = cli.execute(['--version'])
print(result.stdout)
```

### Extension Management

```python
from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI

cli = VSCodeCLI()

# List installed extensions
extensions = cli.list_extensions()
for ext in extensions:
    print(f"- {ext}")

# Install an extension
success = cli.install_extension('ms-python.python')
if success:
    print("Python extension installed")

# Uninstall an extension
success = cli.uninstall_extension('ms-python.python')
if success:
    print("Python extension uninstalled")
```

### Tunnel Management

```python
from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI

cli = VSCodeCLI()

# Login to tunnel service (GitHub authentication)
result = cli.tunnel_user_login(provider='github')
if result.returncode == 0:
    print("Logged in successfully")

# Install tunnel as a service
result = cli.tunnel_service_install(name='my-tunnel')
if result.returncode == 0:
    print("Tunnel service installed")
```

### Custom Installation Directory

```python
from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI

# Use custom installation directory
cli = VSCodeCLI(install_dir='/opt/vscode-cli')
cli.download_and_install()
```

## CLI Usage

### Status Command

Check VSCode CLI installation status:

```bash
# Basic status
ipfs-datasets vscode status

# JSON output
ipfs-datasets vscode status --json

# Custom install directory
ipfs-datasets vscode status --install-dir /opt/vscode-cli
```

### Install Command

Download and install VSCode CLI:

```bash
# Basic installation
ipfs-datasets vscode install

# Force reinstall
ipfs-datasets vscode install --force

# Custom install directory
ipfs-datasets vscode install --install-dir /opt/vscode-cli

# Specific commit/version
ipfs-datasets vscode install --commit <commit-hash>
```

### Execute Command

Execute arbitrary VSCode CLI commands:

```bash
# Get version
ipfs-datasets vscode execute --version

# List extensions
ipfs-datasets vscode execute --list-extensions

# Multiple arguments
ipfs-datasets vscode execute tunnel --help

# With timeout
ipfs-datasets vscode execute --version --timeout 30
```

### Extensions Command

Manage VSCode extensions:

```bash
# List installed extensions
ipfs-datasets vscode extensions list

# Install an extension
ipfs-datasets vscode extensions install ms-python.python

# Uninstall an extension
ipfs-datasets vscode extensions uninstall ms-python.python

# JSON output
ipfs-datasets vscode extensions list --json
```

### Tunnel Command

Manage VSCode tunnel functionality:

```bash
# Login with GitHub
ipfs-datasets vscode tunnel login --provider github

# Login with Microsoft
ipfs-datasets vscode tunnel login --provider microsoft

# Install tunnel as a service
ipfs-datasets vscode tunnel install-service

# Install with custom name
ipfs-datasets vscode tunnel install-service --name my-tunnel
```

## MCP Tool Integration

The VSCode CLI is available as MCP tools for AI assistant integration.

### Available MCP Tools

1. **vscode_cli_status** - Get installation status and information
2. **vscode_cli_install** - Install or update VSCode CLI
3. **vscode_cli_execute** - Execute VSCode CLI commands
4. **vscode_cli_extensions** - Manage VSCode extensions
5. **vscode_cli_tunnel** - Manage VSCode tunnel functionality

### Using MCP Tools from Python

```python
from ipfs_datasets_py.mcp_tools.tools.vscode_cli_tools import VSCodeCLIStatusTool

# Initialize tool
tool = VSCodeCLIStatusTool()

# Execute tool
result = await tool.execute({})
print(result)
```

### Using MCP Tools via MCP Server

The tools are automatically registered with the MCP server when it starts. They can be accessed through:

1. **MCP Server API** - HTTP endpoints at `/api/mcp/tools/development/vscode_cli_*`
2. **MCP Dashboard** - Web GUI for interactive tool execution
3. **MCP JavaScript SDK** - Client library for web applications

Example via MCP Server API:

```bash
# Get status
curl -X GET http://localhost:8899/api/mcp/tools/development/vscode_cli_status/execute

# Install VSCode CLI
curl -X POST http://localhost:8899/api/mcp/tools/development/vscode_cli_install/execute \
  -H "Content-Type: application/json" \
  -d '{"force": false}'

# Execute command
curl -X POST http://localhost:8899/api/mcp/tools/development/vscode_cli_execute/execute \
  -H "Content-Type: application/json" \
  -d '{"command": ["--version"], "timeout": 60}'
```

## Configuration

### Default Installation Directory

By default, VSCode CLI is installed to `~/.vscode-cli`. You can customize this:

```python
from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI

cli = VSCodeCLI(install_dir='/custom/path')
```

Or via CLI:

```bash
ipfs-datasets vscode install --install-dir /custom/path
```

### Commit/Version Selection

By default, the stable version is installed. You can specify a specific commit:

```python
cli = VSCodeCLI(commit='7d842fb85a0275a4a8e4d7e040d2625abbf7f084')
```

Or via CLI:

```bash
ipfs-datasets vscode install --commit 7d842fb85a0275a4a8e4d7e040d2625abbf7f084
```

## Platform Support

The VSCode CLI integration supports:

- **Linux** - x64 and arm64
- **macOS** - x64 and arm64  
- **Windows** - x64 and arm64

The correct version is automatically detected based on your system.

## API Reference

### VSCodeCLI Class

```python
class VSCodeCLI:
    def __init__(self, install_dir: Optional[str] = None, commit: Optional[str] = None)
    def is_installed(self) -> bool
    def download_and_install(self, force: bool = False) -> bool
    def execute(self, args: List[str], capture_output: bool = True, timeout: Optional[int] = None) -> subprocess.CompletedProcess
    def get_version(self) -> Optional[str]
    def get_status(self) -> Dict[str, Any]
    def list_extensions(self) -> List[str]
    def install_extension(self, extension_id: str) -> bool
    def uninstall_extension(self, extension_id: str) -> bool
    def tunnel_user_login(self, provider: str = 'github') -> subprocess.CompletedProcess
    def tunnel_service_install(self, name: Optional[str] = None) -> subprocess.CompletedProcess
```

## Examples

### Complete Workflow Example

```python
from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI

# Initialize
cli = VSCodeCLI()

# Install if not already installed
if not cli.is_installed():
    print("Installing VSCode CLI...")
    success = cli.download_and_install()
    if not success:
        print("Installation failed")
        exit(1)

# Get status
status = cli.get_status()
print(f"Version: {status['version']}")
print(f"Platform: {status['platform']}")
print(f"Architecture: {status['architecture']}")

# Install Python extension
print("Installing Python extension...")
if cli.install_extension('ms-python.python'):
    print("Python extension installed")

# List all extensions
extensions = cli.list_extensions()
print(f"Installed extensions: {len(extensions)}")
for ext in extensions:
    print(f"  - {ext}")

# Execute a custom command
result = cli.execute(['--version'])
if result.returncode == 0:
    print(f"VSCode CLI version:\n{result.stdout}")
```

## Troubleshooting

### Installation Issues

If installation fails:

1. Check network connectivity
2. Verify you have write permissions to the installation directory
3. Try with `force=True` to reinstall
4. Check the commit hash is valid

### Command Execution Issues

If commands fail:

1. Verify VSCode CLI is installed with `cli.is_installed()`
2. Check command syntax matches VSCode CLI documentation
3. Increase timeout for long-running commands
4. Check stdout/stderr for error messages

### Extension Management Issues

If extension operations fail:

1. Verify the extension ID is correct
2. Check network connectivity to VSCode marketplace
3. Ensure VSCode CLI is properly installed

## Contributing

To add new features or fix bugs:

1. Module code: `ipfs_datasets_py/utils/vscode_cli.py`
2. MCP tools: `ipfs_datasets_py/mcp_tools/tools/vscode_cli_tools.py`
3. MCP server tools: `ipfs_datasets_py/mcp_server/tools/development_tools/vscode_cli_tools.py`
4. CLI integration: `ipfs_datasets_cli.py`
5. Tests: `tests/test_vscode_cli.py`

## License

This integration is part of the IPFS Datasets Python package and follows the same license.
